#!/usr/bin/env python3
"""Safely update impstack-owned harness instruction files."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
from dataclasses import dataclass

MAX_BACKUPS = 5


@dataclass(frozen=True)
class Plan:
    key: str
    path: pathlib.Path
    desired: bytes
    action: str
    existing: bytes | None


@dataclass(frozen=True)
class ProtectedPlan:
    plan: Plan
    backup_path: pathlib.Path | None


@dataclass(frozen=True)
class StateObservation:
    recorded: dict[str, str]
    read_diagnostic: str | None


class InstructionFilesystemError(OSError):
    pass


def filesystem_error(path: pathlib.Path, error: OSError) -> InstructionFilesystemError:
    detail = error.strerror or str(error)
    return InstructionFilesystemError(f"could not write instruction file: {path}: {detail}")


def state_diagnostic(path: pathlib.Path, detail: str) -> str:
    return f"could not read instruction state: {path}: {detail}; remove or repair this file"


def rendered(body: bytes) -> bytes:
    digest = hashlib.sha256(body).hexdigest()
    return f"<!-- impstack-managed: instructions sha256={digest} -->\n".encode() + body


def file_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def classify(key: str, path: pathlib.Path, desired: bytes, legacy: bytes, recorded: str | None) -> Plan:
    try:
        if not path.exists():
            return Plan(key, path, desired, "replace", None)
        existing = path.read_bytes()
    except OSError as error:
        raise InstructionFilesystemError(
            f"could not read instruction file: {path}: {error.strerror or error}"
        ) from None
    if existing == desired:
        return Plan(key, path, desired, "noop", existing)
    if recorded == file_digest(existing):
        return Plan(key, path, desired, "replace", existing)
    if existing == legacy:
        return Plan(key, path, desired, "replace", existing)
    return Plan(key, path, desired, "conflict", existing)


def observe_state(path: pathlib.Path) -> StateObservation:
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return StateObservation({}, None)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return StateObservation({}, state_diagnostic(path, str(error)))
    except OSError as error:
        return StateObservation({}, state_diagnostic(path, error.strerror or str(error)))
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("targets"), dict):
        return StateObservation({}, state_diagnostic(path, "invalid format"))
    targets = raw["targets"]
    if not all(
        isinstance(key, str)
        and isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value)
        for key, value in targets.items()
    ):
        return StateObservation({}, state_diagnostic(path, "invalid target digest"))
    return StateObservation(targets, None)


def write_state(path: pathlib.Path, targets: dict[str, str]) -> None:
    content = json.dumps({"version": 1, "targets": dict(sorted(targets.items()))}, indent=2) + "\n"
    replace(path, content.encode())


def backup(path: pathlib.Path, content: bytes) -> pathlib.Path:
    try:
        digest = hashlib.sha256(content).hexdigest()[:12]
        base = path.with_name(f"{path.name}.impstack-backup.{digest}")
        candidate = base
        counter = 1
        while candidate.exists():
            candidate = pathlib.Path(f"{base}.{counter}")
            counter += 1
        candidate.write_bytes(content)
        older_backups = sorted(
            (item for item in path.parent.glob(f"{path.name}.impstack-backup.*") if item != candidate),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
        )
        excess = max(0, len(older_backups) + 1 - MAX_BACKUPS)
        for expired in older_backups[:excess]:
            expired.unlink()
            print(f"removed old backup: {expired}")
        return candidate
    except OSError as error:
        raise filesystem_error(path, error) from None


def show_diff(path: pathlib.Path, existing: bytes, desired: bytes) -> None:
    before = existing.decode(errors="replace").splitlines(keepends=True)
    after = desired.decode(errors="replace").splitlines(keepends=True)
    sys.stdout.writelines(
        difflib.unified_diff(before, after, fromfile=f"existing:{path}", tofile=f"generated:{path}", n=2)
    )


def stage(path: pathlib.Path, content: bytes) -> pathlib.Path:
    temporary: pathlib.Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as output:
            temporary = pathlib.Path(output.name)
            output.write(content)
        return temporary
    except OSError as error:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise filesystem_error(path, error) from None


def commit(temporary: pathlib.Path, path: pathlib.Path) -> None:
    try:
        os.replace(temporary, path)
    except OSError as error:
        raise filesystem_error(path, error) from None


def replace(path: pathlib.Path, content: bytes) -> None:
    temporary = stage(path, content)
    try:
        commit(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def protect(plan: Plan) -> ProtectedPlan:
    if plan.action == "noop" or plan.existing is None:
        return ProtectedPlan(plan, None)
    saved = backup(plan.path, plan.existing)
    print(f"backup: {saved}")
    return ProtectedPlan(plan, saved)


def stage_replacement(protected: ProtectedPlan) -> pathlib.Path:
    plan = protected.plan
    assert plan.action != "noop"
    assert plan.existing is None or protected.backup_path is not None
    return stage(plan.path, plan.desired)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--home", type=pathlib.Path, required=True)
    parser.add_argument("--private", type=pathlib.Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    state_root = pathlib.Path(os.environ.get("XDG_STATE_HOME", args.home / ".local/state"))
    state_path = state_root.expanduser().resolve() / "impstack" / "instructions.json"
    observation = observe_state(state_path)
    recorded = observation.recorded.copy()

    private_exists = (args.private / "AGENTS.md").is_file()
    claude_body = b"@AGENTS.portable.md\n" + (b"@AGENTS.private.md\n" if private_exists else b"")
    codex_parts = [(args.root / "conventions/AGENTS.md").read_bytes()]
    if private_exists:
        codex_parts.append((args.private / "AGENTS.md").read_bytes())
    codex_parts.append((args.root / "configs/pstack-codex.md").read_bytes())
    codex_body = b"\n\n".join(part.rstrip(b"\n") for part in codex_parts) + b"\n"
    old_codex = (
        "<!-- GENERATED by impstack/install.sh — edit the source repos, then re-run -->\n\n".encode()
        + codex_body
    )

    plans = (
        classify(
            ".claude/CLAUDE.md",
            args.home / ".claude/CLAUDE.md",
            rendered(claude_body),
            claude_body,
            recorded.get(".claude/CLAUDE.md"),
        ),
        classify(
            "AGENTS.md",
            args.home / "AGENTS.md",
            rendered(codex_body),
            old_codex,
            recorded.get("AGENTS.md"),
        ),
    )
    conflicts = [plan for plan in plans if plan.action == "conflict"]
    ready = plans if args.force else tuple(plan for plan in plans if plan.action != "conflict")
    if observation.read_diagnostic and any(plan.action != "noop" for plan in plans):
        print(f"warning: {observation.read_diagnostic}", file=sys.stderr)

    protected_plans = tuple(protect(plan) for plan in plans)
    ready_keys = {plan.key for plan in ready}

    staged: list[tuple[ProtectedPlan, pathlib.Path]] = []
    try:
        for protected in protected_plans:
            plan = protected.plan
            if plan.key not in ready_keys:
                continue
            if plan.action != "noop":
                staged.append((protected, stage_replacement(protected)))
        for protected, temporary in staged:
            plan = protected.plan
            commit(temporary, plan.path)
            print(f"managed: {plan.path}")
        for plan in ready:
            recorded[plan.key] = file_digest(plan.desired)
        write_state(state_path, recorded)
    finally:
        for _, temporary in staged:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    if not args.force:
        for plan in conflicts:
            assert plan.existing is not None
            show_diff(plan.path, plan.existing, plan.desired)
            print(
                f"blocked instruction file: {plan.path}; examine the backup and diff, then use --force",
                file=sys.stderr,
            )
    return 1 if conflicts and not args.force else 0


if __name__ == "__main__":
    try:
        exit_code = main(sys.argv[1:])
    except InstructionFilesystemError as error:
        print(f"error: {error}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)
