#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import os
import pathlib
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence


class Status(enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not-applicable"


class WorkingDirectory(enum.Enum):
    REPO = "repo"
    OUTSIDE_PROJECT = "outside-project"


@dataclasses.dataclass(frozen=True)
class Applicability:
    applicable: bool
    reason: str | None
    remediation_actionable: bool


@dataclasses.dataclass(frozen=True)
class Assertion:
    assertion_id: str
    kind: str
    requirements: tuple[Mapping[str, str], ...]
    working_directory: WorkingDirectory
    command: tuple[str, ...]
    exit_code: int
    stdout_contains: str | None
    remediation_kind: str
    remediation_text: str
    remediation_stage_id: str | None
    remediation_statuses: tuple[Status, ...]
    absent_registration_reason: str | None
    absent_registration_exit_codes: tuple[int, ...]
    absent_registration_requires_missing_stdout: bool


@dataclasses.dataclass(frozen=True)
class CommandEvidence:
    command: str
    exit_code: int | None
    stdout: str
    stderr: str


@dataclasses.dataclass(frozen=True)
class AssertionResult:
    assertion_id: str
    status: Status
    message: str
    evidence: CommandEvidence
    applicability: Applicability
    remediation_kind: str
    remediation_text: str
    remediation_stage_id: str | None
    remediation_statuses: tuple[Status, ...]


@dataclasses.dataclass(frozen=True)
class Report:
    results: tuple[AssertionResult, ...]

    @property
    def failed(self) -> bool:
        return any(result.status is Status.FAIL for result in self.results)


@dataclasses.dataclass(frozen=True)
class Context:
    repo: pathlib.Path
    home: pathlib.Path
    environment: Mapping[str, str]
    outside_project: pathlib.Path


WIZARD_STAGES = {
    "claude-login": "Claude login",
    "codex-login": "Codex login",
    "opencode-login": "OpenCode login",
    "context7-token": "Context7 token",
    "executor-connection": "Executor connection",
}


def _expect_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def load_contract(path: pathlib.Path) -> tuple[Assertion, ...]:
    document = _expect_mapping(json.loads(path.read_text()), "contract")
    if document.get("version") != 1 or not isinstance(document.get("assertions"), list):
        raise ValueError("contract must have version 1 and an assertions array")
    assertions: list[Assertion] = []
    seen: set[str] = set()
    for index, raw in enumerate(document["assertions"]):
        item = _expect_mapping(raw, f"assertions[{index}]")
        assertion_id = item.get("id")
        command = item.get("command")
        requirements = item.get("applicability")
        working_directory = item.get("working_directory")
        expectation = _expect_mapping(item.get("expectation"), f"{assertion_id}.expectation")
        remediation = _expect_mapping(item.get("remediation"), f"{assertion_id}.remediation")
        valid = (
            isinstance(assertion_id, str)
            and assertion_id
            and assertion_id not in seen
            and item.get("kind") in {"command", "shared-path"}
            and isinstance(command, list)
            and command
            and all(isinstance(part, str) and part for part in command)
            and isinstance(requirements, list)
            and all(isinstance(requirement, dict) for requirement in requirements)
            and working_directory in {item.value for item in WorkingDirectory}
            and isinstance(expectation.get("exit_code"), int)
            and (
                expectation.get("stdout_contains") is None
                or isinstance(expectation.get("stdout_contains"), str)
            )
            and remediation.get("kind") in {"command", "wizard"}
        )
        if not valid:
            raise ValueError(f"invalid assertion: {assertion_id or index}")
        remediation_text = remediation.get("text", remediation.get("stage"))
        remediation_statuses = remediation.get("statuses")
        remediation_stage_id = remediation.get("stage_id")
        absent_registration = item.get("absent_registration")
        if (
            not isinstance(remediation_text, str)
            or not remediation_text
            or not isinstance(remediation_statuses, list)
            or not remediation_statuses
            or not all(status in {item.value for item in Status} for status in remediation_statuses)
            or (
                remediation.get("kind") == "wizard"
                and (
                    remediation_stage_id not in WIZARD_STAGES
                    or WIZARD_STAGES[remediation_stage_id] != remediation_text
                )
            )
            or (remediation.get("kind") == "command" and remediation_stage_id is not None)
        ):
            raise ValueError(f"invalid remediation: {assertion_id}")
        absent_reason: str | None = None
        absent_exit_codes: tuple[int, ...] = ()
        absent_requires_missing_stdout = False
        if absent_registration is not None:
            absent = _expect_mapping(absent_registration, f"{assertion_id}.absent_registration")
            raw_exit_codes = absent.get("exit_codes")
            absent_requires_missing_stdout = absent.get("requires_missing_stdout") is True
            if (
                absent.get("status") != Status.NOT_APPLICABLE.value
                or not isinstance(absent.get("reason"), str)
                or not isinstance(raw_exit_codes, list)
                or not raw_exit_codes
                or not all(isinstance(code, int) for code in raw_exit_codes)
            ):
                raise ValueError(f"invalid absent registration: {assertion_id}")
            absent_reason = str(absent["reason"])
            absent_exit_codes = tuple(raw_exit_codes)
        for requirement in requirements:
            if requirement.get("kind") not in {"command", "environment"} or not isinstance(
                requirement.get("actionable"), bool
            ):
                raise ValueError(f"invalid applicability rule: {assertion_id}")
        seen.add(assertion_id)
        assertions.append(
            Assertion(
                assertion_id=assertion_id,
                kind=str(item["kind"]),
                requirements=tuple(requirements),
                working_directory=WorkingDirectory(str(working_directory)),
                command=tuple(command),
                exit_code=int(expectation["exit_code"]),
                stdout_contains=expectation.get("stdout_contains"),
                remediation_kind=str(remediation["kind"]),
                remediation_text=remediation_text,
                remediation_stage_id=(
                    str(remediation_stage_id) if remediation_stage_id is not None else None
                ),
                remediation_statuses=tuple(Status(status) for status in remediation_statuses),
                absent_registration_reason=absent_reason,
                absent_registration_exit_codes=absent_exit_codes,
                absent_registration_requires_missing_stdout=absent_requires_missing_stdout,
            )
        )
    return tuple(assertions)


def _applicability(assertion: Assertion, context: Context) -> Applicability:
    for requirement in assertion.requirements:
        kind = requirement.get("kind")
        name = requirement.get("name")
        if not isinstance(name, str):
            raise ValueError(f"invalid applicability rule: {assertion.assertion_id}")
        if kind == "command" and shutil.which(name, path=context.environment.get("PATH")) is None:
            return Applicability(False, f"{name} is not installed", bool(requirement["actionable"]))
        if kind == "environment" and name not in context.environment:
            return Applicability(False, f"${name} is not set", bool(requirement["actionable"]))
        if kind not in {"command", "environment"}:
            raise ValueError(f"unknown applicability rule: {kind}")
    return Applicability(True, None, True)


def _safe_output(text: str, assertion_id: str) -> str:
    text = text.replace("\x00", "")
    if ".executor." in assertion_id:
        text = re.sub(r"https?://\S+", "<redacted-url>", text)
    text = re.sub(
        r"(?i)(token|secret|password|api[_-]?key)(\s*[:=]\s*)\S+",
        r"\1\2<redacted>",
        text,
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-3:])[:600]


def _run(assertion: Assertion, context: Context) -> CommandEvidence:
    command = tuple(part.replace("{repo}", str(context.repo)) for part in assertion.command)
    environment = dict(context.environment)
    environment["HOME"] = str(context.home)
    environment["IMPSTACK_DIR"] = str(context.repo)
    environment["COMMISSION_ASSERTION_ID"] = assertion.assertion_id
    try:
        completed = subprocess.run(
            command,
            cwd=(
                context.repo
                if assertion.working_directory is WorkingDirectory.REPO
                else context.outside_project
            ),
            env=environment,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        return CommandEvidence(
            command=shlex.join(command),
            exit_code=completed.returncode,
            stdout=_safe_output(completed.stdout, assertion.assertion_id),
            stderr=_safe_output(completed.stderr, assertion.assertion_id),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return CommandEvidence(
            command=shlex.join(command),
            exit_code=None,
            stdout="",
            stderr=_safe_output(str(error), assertion.assertion_id),
        )


def evaluate(assertions: Sequence[Assertion], context: Context) -> Report:
    results: list[AssertionResult] = []
    for assertion in assertions:
        applicability = _applicability(assertion, context)
        if not applicability.applicable:
            evidence = CommandEvidence(shlex.join(assertion.command), None, "", "")
            results.append(
                AssertionResult(
                    assertion.assertion_id,
                    Status.NOT_APPLICABLE,
                    applicability.reason or "not applicable",
                    evidence,
                    applicability,
                    assertion.remediation_kind,
                    assertion.remediation_text,
                    assertion.remediation_stage_id,
                    assertion.remediation_statuses,
                )
            )
            continue
        evidence = _run(assertion, context)
        matches_exit = evidence.exit_code == assertion.exit_code
        matches_stdout = (
            assertion.stdout_contains is None
            or assertion.stdout_contains in evidence.stdout
        )
        if assertion.kind == "shared-path" and matches_exit:
            expected = pathlib.Path(
                context.environment.get("SHARED_SKILLS", context.home / ".agents" / "skills")
            ).expanduser().resolve()
            try:
                actual = pathlib.Path(evidence.stdout).expanduser().resolve()
            except (OSError, RuntimeError):
                actual = pathlib.Path("/__invalid_shared_path__")
            sources = (context.repo / "install.sh", context.repo / "bin" / "skills-update")
            resolver_call = 'bin/skills-sync" resolve-shared'
            matches_stdout = actual == expected and all(
                source.is_file() and resolver_call in source.read_text() for source in sources
            )
        status = Status.PASS if matches_exit and matches_stdout else Status.FAIL
        absent_registration = (
            status is Status.FAIL
            and assertion.absent_registration_reason is not None
            and evidence.exit_code in assertion.absent_registration_exit_codes
            and (
                not assertion.absent_registration_requires_missing_stdout
                or (
                    assertion.stdout_contains is not None
                    and assertion.stdout_contains not in evidence.stdout
                )
            )
        )
        if absent_registration:
            status = Status.NOT_APPLICABLE
            applicability = Applicability(
                False, assertion.absent_registration_reason, False
            )
        if status is Status.PASS:
            message = "expectation met"
        elif status is Status.NOT_APPLICABLE:
            message = assertion.absent_registration_reason or "not applicable"
        elif not matches_exit:
            message = f"expected exit {assertion.exit_code}, got {evidence.exit_code}"
        elif assertion.kind == "shared-path":
            message = "shared path or resolver callers do not match"
        else:
            message = f"stdout does not contain {assertion.stdout_contains!r}"
        results.append(
            AssertionResult(
                assertion.assertion_id,
                status,
                message,
                evidence,
                applicability,
                assertion.remediation_kind,
                assertion.remediation_text,
                assertion.remediation_stage_id,
                assertion.remediation_statuses,
            )
        )
    return Report(tuple(results))


def report_data(report: Report) -> dict[str, object]:
    return {
        "version": 1,
        "assertions": [
            {
                "id": result.assertion_id,
                "status": result.status.value,
                "message": result.message,
                "command": result.evidence.command,
                "exit_code": result.evidence.exit_code,
                "remediation": {
                    "kind": result.remediation_kind,
                    "text": result.remediation_text,
                    **(
                        {"stage_id": result.remediation_stage_id}
                        if result.remediation_stage_id
                        else {}
                    ),
                },
            }
            for result in report.results
        ],
    }


def render_report(report: Report, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report_data(report), indent=2) + "\n"
    lines = []
    for result in report.results:
        lines.append(
            f"{result.status.value:14} {result.assertion_id}: {result.message}; "
            f"command={result.evidence.command}"
        )
    return "\n".join(lines) + "\n"


def _result(report: Report, assertion_id: str) -> AssertionResult | None:
    return next((item for item in report.results if item.assertion_id == assertion_id), None)


def _version(command: str, context: Context) -> str:
    if shutil.which(command, path=context.environment.get("PATH")) is None:
        return "not installed"
    assertion = Assertion(
        "inventory", "command", (), WorkingDirectory.REPO, (command, "--version"),
        0, None, "command", "none", None, (Status.FAIL,), None, (), False,
    )
    evidence = _run(assertion, context)
    return evidence.stdout or evidence.stderr or f"exit {evidence.exit_code}"


def _runtime_value(report: Report, assertion_id: str) -> str:
    result = _result(report, assertion_id)
    if result is None or result.status is not Status.PASS:
        return "unavailable"
    return result.evidence.stdout


def render_record(report: Report, context: Context, wizard_path: pathlib.Path | None) -> str:
    hostname = socket.gethostname()
    safe_hostname = re.sub(r"[^a-z0-9-]+", "-", hostname.lower()).strip("-") or "unknown"
    container = pathlib.Path("/.dockerenv").exists() or pathlib.Path("/run/.containerenv").exists()
    shared = _runtime_value(report, "skills.shared-path")
    node_path = _runtime_value(report, "runtime.node")
    npx_path = _runtime_value(report, "runtime.npx")
    bun_path = shutil.which("bun", path=context.environment.get("PATH")) or "not installed"
    xdg = context.environment.get("XDG_STATE_HOME", "not set")
    lines = [
        "---",
        f"name: machine-{safe_hostname}",
        "description: Use for setup, troubleshooting, or provisioning on this machine.",
        "---",
        "",
        f"# Machine {hostname}",
        "",
        "## Identity",
        "",
        f"- Hostname: `{hostname}`",
        f"- OS: `{platform.system()} {platform.release()}`",
        f"- Container: `{'yes' if container else 'no'}`",
        f"- Shell: `{context.environment.get('SHELL', 'unknown')}`",
        "",
        "## Runtime",
        "",
        f"- Node: `{node_path}`. Version: `{_version('node', context)}`",
        f"- npx: `{npx_path}`. Version: `{_version('npx', context)}`",
        f"- Bun: `{bun_path}`. Version: `{_version('bun', context)}`",
        f"- Package manager: `{shutil.which('npm', path=context.environment.get('PATH')) or 'unavailable'}`. "
        f"Version: `{_runtime_value(report, 'runtime.package-manager')}`",
        f"- XDG state home: `{xdg}`",
        f"- Shared skills: `{shared}`",
        "",
        "## Harnesses",
        "",
        "| Harness | Installed | Version | Authenticated | Conventions |",
        "|---|---|---|---|---|",
    ]
    for harness in ("claude", "codex", "opencode"):
        auth = _result(report, f"harness.{harness}.auth")
        canary = _result(report, f"harness.{harness}.canary")
        installed = auth is not None and auth.status is not Status.NOT_APPLICABLE
        lines.append(
            f"| {harness} | {'yes' if installed else 'no'} | {_version(harness, context)} | "
            f"{auth.status.value if auth else 'unknown'} | "
            f"{canary.status.value if canary else 'unknown'} |"
        )
    lines.extend(["", "## Connections", ""])
    for result in report.results:
        if result.assertion_id.startswith("mcp."):
            _, server, harness = result.assertion_id.split(".")
            lines.append(f"- {server} for {harness}: `{result.status.value}`. {result.message}")
    lines.extend(["", "## Contract", ""])
    for result in report.results:
        lines.append(
            f"- `{result.assertion_id}`: `{result.status.value}`. Command: `{result.evidence.command}`. {result.message}"
        )
    lines.extend(["", "## Remediation", ""])
    actionable = [
        result
        for result in report.results
        if result.status in result.remediation_statuses
        and (
            result.status is not Status.NOT_APPLICABLE
            or result.applicability.remediation_actionable
        )
    ]
    if actionable:
        for result in actionable:
            remediation = (
                f"Run wizard stage `{result.remediation_text}` from `{wizard_path}`."
                if result.remediation_kind == "wizard" and wizard_path
                else result.remediation_text
            )
            lines.append(f"- `{result.assertion_id}`: {remediation}")
    else:
        lines.append("- No failed assertions require remediation.")
    return "\n".join(lines) + "\n"


def render_wizard(template: str, report: Report) -> str:
    marker = "# STAGES: author this section. One stage() per step the human takes."
    if template.count(marker) != 1:
        raise ValueError("wizard template must contain one STAGES marker")
    library = template[: template.index(marker)]
    stages: list[tuple[str, str]] = []
    for result in report.results:
        if (
            result.remediation_kind != "wizard"
            or result.status not in result.remediation_statuses
            or (
                result.status is Status.NOT_APPLICABLE
                and not result.applicability.remediation_actionable
            )
        ):
            continue
        stage = (result.remediation_stage_id or "", result.remediation_text)
        if stage not in stages:
            stages.append(stage)
    lines = [
        marker,
        "",
        f"TOTAL_STAGES={len(stages)}",
        'banner "Commission this machine"',
        "",
    ]
    for stage_id, stage_name in stages:
        lines.append(f'stage "{stage_name}"')
        if stage_id == "executor-connection":
            lines.extend(
                [
                    'ENV_FILE="$HOME/.config/impstack/env"',
                    'mkdir -p "$(dirname "$ENV_FILE")"',
                    'say "Paste the Executor MCP URL. Input stays hidden."',
                    'ask_secret EXECUTOR_MCP_URL "Executor MCP URL:"',
                    'write_env EXECUTOR_MCP_URL "$EXECUTOR_MCP_URL"',
                    'say "To use the saved value, source $ENV_FILE, then run ./install.sh mcp."',
                    'open_url "$EXECUTOR_MCP_URL" >/dev/null',
                    'say "After the page opens, complete the browser sign-in and return here."',
                    'pause "Press Enter after you complete the browser sign-in."',
                ]
            )
        elif stage_id == "context7-token":
            lines.extend(
                [
                    'ENV_FILE="$HOME/.config/impstack/env"',
                    'mkdir -p "$(dirname "$ENV_FILE")"',
                    'open_url "https://context7.com/dashboard"',
                    'step "Create an API key, then copy it before you close the dialog."',
                    'ask_secret CONTEXT7_API_KEY "Context7 API key:"',
                    'write_env CONTEXT7_API_KEY "$CONTEXT7_API_KEY"',
                    'say "To use the saved value, source $ENV_FILE, then run ./install.sh mcp."',
                ]
            )
        else:
            harness = {
                "claude-login": "Claude",
                "codex-login": "Codex",
                "opencode-login": "OpenCode",
            }[stage_id]
            command = {
                "Claude": "claude auth login",
                "Codex": "codex login",
                "OpenCode": "opencode auth login",
            }[harness]
            lines.extend(
                [
                    f'say "{command} opens the {harness} sign-in flow."',
                    f'if confirm "Start {harness} sign-in?"; then {command}; else SKIPPED+=("{harness} sign-in"); fi',
                ]
            )
        lines.append("")
    lines.extend(["finish", ""])
    return library + "\n".join(lines)


def _context(args: argparse.Namespace, outside_project: pathlib.Path) -> Context:
    return Context(
        args.repo.resolve(), args.home.resolve(), dict(os.environ), outside_project.resolve()
    )


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home())
    parser.add_argument("--contract", type=pathlib.Path)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe a machine against the impstack contract.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    check = subparsers.add_parser("check")
    _common(check)
    check.add_argument("--format", choices=("text", "json"), default="text")
    probe = subparsers.add_parser("probe")
    _common(probe)
    probe.add_argument("--record", type=pathlib.Path, required=True)
    probe.add_argument("--wizard", type=pathlib.Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    try:
        repo = args.repo.resolve()
        home = args.home.resolve()
        outside_root = home / ".cache" / "impstack" / "commission"
        outside_root.mkdir(parents=True, exist_ok=True)
        if outside_root == repo or repo in outside_root.parents:
            raise ValueError("outside-project directory must be outside the repository")
        with tempfile.TemporaryDirectory(dir=outside_root) as temporary_directory:
            context = _context(args, pathlib.Path(temporary_directory))
            contract_path = args.contract or context.repo / "commission.contract.json"
            report = evaluate(load_contract(contract_path), context)
        if args.action == "check":
            sys.stdout.write(render_report(report, args.format))
        else:
            wizard_path = args.wizard
            if wizard_path:
                shared_result = _result(report, "skills.shared-path")
                if shared_result is None or shared_result.status is not Status.PASS:
                    raise ValueError("skills.shared-path must pass before wizard generation")
                template_path = pathlib.Path(shared_result.evidence.stdout) / "wizard" / "template.sh"
                wizard_path.parent.mkdir(parents=True, exist_ok=True)
                wizard_path.write_text(render_wizard(template_path.read_text(), report))
                wizard_path.chmod(0o700)
            args.record.parent.mkdir(parents=True, exist_ok=True)
            args.record.write_text(render_record(report, context, wizard_path))
            print(f"record wrote {args.record}")
            if wizard_path:
                print(f"wizard wrote {wizard_path}")
        return 1 if report.failed else 0
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
