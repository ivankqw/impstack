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
from collections.abc import Mapping, Sequence


class Status(enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not-applicable"


@dataclasses.dataclass(frozen=True)
class Assertion:
    assertion_id: str
    kind: str
    requirements: tuple[Mapping[str, str], ...]
    command: tuple[str, ...]
    exit_code: int
    stdout_contains: str | None
    remediation_kind: str
    remediation_text: str
    remediation_statuses: tuple[Status, ...]


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
    remediation_kind: str
    remediation_text: str
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
        if (
            not isinstance(remediation_text, str)
            or not remediation_text
            or not isinstance(remediation_statuses, list)
            or not remediation_statuses
            or not all(status in {item.value for item in Status} for status in remediation_statuses)
        ):
            raise ValueError(f"invalid remediation: {assertion_id}")
        seen.add(assertion_id)
        assertions.append(
            Assertion(
                assertion_id=assertion_id,
                kind=str(item["kind"]),
                requirements=tuple(requirements),
                command=tuple(command),
                exit_code=int(expectation["exit_code"]),
                stdout_contains=expectation.get("stdout_contains"),
                remediation_kind=str(remediation["kind"]),
                remediation_text=remediation_text,
                remediation_statuses=tuple(Status(status) for status in remediation_statuses),
            )
        )
    return tuple(assertions)


def _not_applicable(assertion: Assertion, context: Context) -> str | None:
    for requirement in assertion.requirements:
        kind = requirement.get("kind")
        name = requirement.get("name")
        if not isinstance(name, str):
            raise ValueError(f"invalid applicability rule: {assertion.assertion_id}")
        if kind == "command" and shutil.which(name, path=context.environment.get("PATH")) is None:
            return f"{name} is not installed"
        if kind == "environment" and name not in context.environment:
            return f"${name} is not set"
        if kind not in {"command", "environment"}:
            raise ValueError(f"unknown applicability rule: {kind}")
    return None


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
            cwd=context.repo,
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
        unavailable = _not_applicable(assertion, context)
        if unavailable:
            evidence = CommandEvidence(shlex.join(assertion.command), None, "", "")
            results.append(
                AssertionResult(
                    assertion.assertion_id,
                    Status.NOT_APPLICABLE,
                    unavailable,
                    evidence,
                    assertion.remediation_kind,
                    assertion.remediation_text,
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
        if status is Status.PASS:
            message = "expectation met"
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
                assertion.remediation_kind,
                assertion.remediation_text,
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
        "inventory", "command", (), (command, "--version"), 0, None,
        "command", "none", (Status.FAIL,),
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
        "- Package manager: `npm` through `npx`",
        f"- XDG state home: `{xdg}`",
        f"- Shared skills: `{shared}`",
        "",
        "## Harnesses",
        "",
    ]
    for harness in ("claude", "codex", "opencode"):
        auth = _result(report, f"harness.{harness}.auth")
        canary = _result(report, f"harness.{harness}.canary")
        installed = auth is not None and auth.status is not Status.NOT_APPLICABLE
        lines.append(
            f"- {harness}: installed `{'yes' if installed else 'no'}`; "
            f"version `{_version(harness, context)}`; authenticated `{auth.status.value if auth else 'unknown'}`; "
            f"conventions `{canary.status.value if canary else 'unknown'}`"
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
        result for result in report.results if result.status in result.remediation_statuses
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
    stage_names: list[str] = []
    for result in report.results:
        if (
            result.remediation_kind != "wizard"
            or result.status not in result.remediation_statuses
        ):
            continue
        if result.remediation_text not in stage_names:
            stage_names.append(result.remediation_text)
    lines = [
        marker,
        "",
        f"TOTAL_STAGES={len(stage_names)}",
        'banner "Commission this machine"',
        "",
    ]
    for stage_name in stage_names:
        lines.append(f'stage "{stage_name}"')
        if stage_name == "Executor connection":
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
        elif stage_name == "Context7 token":
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
            harness = stage_name.removesuffix(" login")
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


def _context(args: argparse.Namespace) -> Context:
    return Context(args.repo.resolve(), args.home.resolve(), dict(os.environ))


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
    context = _context(args)
    contract_path = args.contract or context.repo / "commission.contract.json"
    try:
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
