#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import enum
import io
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

try:
    from scripts import managed_instructions as managed
except ModuleNotFoundError:
    import managed_instructions as managed


class Status(enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"
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
    stdout_equals: str | None
    remediation_kind: str
    remediation_text: str
    remediation_stage_id: str | None
    remediation_statuses: tuple[Status, ...]
    absent_registration_reason: str | None
    absent_registration_exit_codes: tuple[int, ...]
    absent_registration_requires_missing_stdout: bool
    absent_registration_stderr_contains: str | None


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
        return any(
            result.status in {Status.FAIL, Status.INDETERMINATE}
            for result in self.results
        )


@dataclasses.dataclass(frozen=True)
class Context:
    repo: pathlib.Path
    home: pathlib.Path
    environment: Mapping[str, str]
    outside_project: pathlib.Path


@dataclasses.dataclass(frozen=True)
class RuntimeRecord:
    name: str
    path: str
    version: str


@dataclasses.dataclass(frozen=True)
class HarnessRecord:
    name: str
    installed: bool
    version: str
    authenticated: bool
    conventions: Status | None


@dataclasses.dataclass(frozen=True)
class ConnectionRecord:
    server: str
    harness: str
    status: Status
    message: str


@dataclasses.dataclass(frozen=True)
class ContractRecord:
    assertion_id: str
    status: Status
    command: str
    message: str


@dataclasses.dataclass(frozen=True)
class RemediationRecord:
    assertion_id: str
    text: str


@dataclasses.dataclass(frozen=True)
class MachineRecord:
    hostname: str
    os_name: str
    os_version: str
    container: bool
    shell: str
    runtimes: tuple[RuntimeRecord, ...]
    xdg_state_home: str
    shared_skills: str
    harnesses: tuple[HarnessRecord, ...]
    connections: tuple[ConnectionRecord, ...]
    contract: tuple[ContractRecord, ...]
    remediations: tuple[RemediationRecord, ...]


@dataclasses.dataclass(frozen=True)
class Artifact:
    key: str
    path: pathlib.Path
    content: bytes
    mode: int


WIZARD_STAGES = {
    "claude-login": "Claude login",
    "codex-login": "Codex login",
    "opencode-login": "OpenCode login",
    "context7-token": "Context7 token",
    "executor-connection": "Executor connection",
}

WIZARD_HELPERS = (
    "banner",
    "stage",
    "say",
    "step",
    "open_url",
    "confirm",
    "ask_secret",
    "write_env",
    "finish",
)


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
            and item.get("kind") in {"command", "shared-path", "canary", "json-canary"}
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
            and (
                expectation.get("stdout_equals") is None
                or isinstance(expectation.get("stdout_equals"), str)
            )
            and not (
                expectation.get("stdout_contains") is not None
                and expectation.get("stdout_equals") is not None
            )
            and (
                item.get("kind") not in {"canary", "json-canary"}
                or (
                    isinstance(expectation.get("stdout_equals"), str)
                    and bool(expectation.get("stdout_equals"))
                )
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
        absent_stderr_contains: str | None = None
        if absent_registration is not None:
            absent = _expect_mapping(absent_registration, f"{assertion_id}.absent_registration")
            raw_exit_codes = absent.get("exit_codes")
            absent_requires_missing_stdout = absent.get("requires_missing_stdout") is True
            absent_stderr_contains = absent.get("stderr_contains")
            if (
                absent.get("status") != Status.NOT_APPLICABLE.value
                or not isinstance(absent.get("reason"), str)
                or not absent.get("reason")
                or not isinstance(raw_exit_codes, list)
                or not raw_exit_codes
                or not all(isinstance(code, int) for code in raw_exit_codes)
                or (
                    absent_stderr_contains is not None
                    and (
                        not isinstance(absent_stderr_contains, str)
                        or not absent_stderr_contains
                    )
                )
                or not (
                    absent_requires_missing_stdout
                    or (
                        isinstance(absent_stderr_contains, str)
                        and bool(absent_stderr_contains)
                    )
                )
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
                stdout_equals=expectation.get("stdout_equals"),
                remediation_kind=str(remediation["kind"]),
                remediation_text=remediation_text,
                remediation_stage_id=(
                    str(remediation_stage_id) if remediation_stage_id is not None else None
                ),
                remediation_statuses=tuple(Status(status) for status in remediation_statuses),
                absent_registration_reason=absent_reason,
                absent_registration_exit_codes=absent_exit_codes,
                absent_registration_requires_missing_stdout=absent_requires_missing_stdout,
                absent_registration_stderr_contains=absent_stderr_contains,
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


def _redact_structured(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(
                marker in normalized
                for marker in ("token", "secret", "password", "apikey")
            ):
                redacted[str(key)] = "<redacted>"
            else:
                redacted[str(key)] = _redact_structured(item)
        return redacted
    if isinstance(value, list):
        return [_redact_structured(item) for item in value]
    return value


def _safe_output(text: str, assertion_id: str) -> str:
    text = text.replace("\x00", "")
    try:
        structured = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    else:
        text = json.dumps(_redact_structured(structured))
    if ".executor." in assertion_id:
        text = re.sub(r"https?://\S+", "<redacted-url>", text)
    text = re.sub(
        r'''(?ix)(
            ["']?[a-z0-9_-]*(?:token|secret|password|api[_-]?key)[a-z0-9_-]*["']?
            \s*[:=]\s*
        )
        (?:"[^"]*"|'[^']*'|[^,\s}\]]+)''',
        r"\1<redacted>",
        text,
    )
    text = re.sub(r'''(?i)\bbearer\s+[^\s"',}\]]+''', "Bearer <redacted>", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-3:])[:600]


def _json_canary_output(text: str) -> str:
    parts: list[str] = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return ""
        if not isinstance(event, dict) or event.get("type") != "text":
            continue
        part = event.get("part")
        if not isinstance(part, dict) or part.get("type") != "text":
            return ""
        value = part.get("text")
        if not isinstance(value, str):
            return ""
        parts.append(value)
    return "".join(parts).strip()


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
            command=shlex.join(assertion.command),
            exit_code=completed.returncode,
            stdout=(
                _safe_output(_json_canary_output(completed.stdout), assertion.assertion_id)
                if assertion.kind == "json-canary"
                else _safe_output(completed.stdout, assertion.assertion_id)
            ),
            stderr=_safe_output(completed.stderr, assertion.assertion_id),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return CommandEvidence(
            command=shlex.join(assertion.command),
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
        matches_stdout = assertion.stdout_contains is None or (
            assertion.stdout_contains in evidence.stdout
        )
        if assertion.stdout_equals is not None:
            matches_stdout = evidence.stdout.strip() == assertion.stdout_equals
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
        if (
            assertion.kind in {"canary", "json-canary"}
            and matches_exit
            and not matches_stdout
            and evidence.stdout.strip() != "MISSING"
        ):
            status = Status.INDETERMINATE
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
            and (
                assertion.absent_registration_stderr_contains is None
                or assertion.absent_registration_stderr_contains in evidence.stderr
            )
        )
        if absent_registration:
            status = Status.NOT_APPLICABLE
            applicability = Applicability(
                False, assertion.absent_registration_reason, False
            )
        if status is Status.PASS:
            message = "expectation met"
        elif status is Status.INDETERMINATE:
            message = "canary response was indeterminate"
        elif status is Status.NOT_APPLICABLE:
            message = assertion.absent_registration_reason or "not applicable"
        elif not matches_exit:
            message = f"expected exit {assertion.exit_code}, got {evidence.exit_code}"
        elif assertion.kind == "shared-path":
            message = "shared path or resolver callers do not match"
        else:
            expected_output = assertion.stdout_equals or assertion.stdout_contains
            message = f"stdout does not match {expected_output!r}"
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


def _selected_version(value: str) -> str:
    match = re.search(r"(?<![A-Za-z0-9])v?(\d+(?:\.\d+)+)(?![A-Za-z0-9])", value)
    return match.group(1) if match else "present"


def _version(command: str, context: Context) -> str:
    if shutil.which(command, path=context.environment.get("PATH")) is None:
        return "not installed"
    assertion = Assertion(
        "inventory", "command", (), WorkingDirectory.REPO, (command, "--version"),
        0, None, None, "command", "none", None, (Status.FAIL,), None, (), False, None,
    )
    evidence = _run(assertion, context)
    return _selected_version(evidence.stdout or evidence.stderr)


def _runtime_value(report: Report, assertion_id: str) -> str | None:
    result = _result(report, assertion_id)
    if result is None or result.status is not Status.PASS:
        return None
    return result.evidence.stdout


def _runtime_version(report: Report, assertion_id: str) -> str:
    value = _runtime_value(report, assertion_id)
    return _selected_version(value) if value is not None else "unavailable"


def _selected_path(
    value: str | pathlib.Path | None,
    known: Mapping[pathlib.Path, str],
    unavailable: str,
) -> str:
    if value is None:
        return unavailable
    try:
        path = pathlib.Path(value).expanduser().resolve()
    except (OSError, RuntimeError):
        return "custom"
    for candidate, label in known.items():
        if path == candidate.expanduser().resolve():
            return label
    return "custom"


def _executable_path(value: str | None, command: str) -> str:
    roots = (
        pathlib.Path("/bin"),
        pathlib.Path("/usr/bin"),
        pathlib.Path("/usr/local/bin"),
        pathlib.Path("/opt/homebrew/bin"),
    )
    return _selected_path(
        value,
        {root / command: str(root / command) for root in roots},
        "not installed",
    )


def _machine_name() -> str:
    hostname = re.sub(r"[^a-z0-9-]+", "-", socket.gethostname().lower()).strip("-")
    return f"machine-{hostname or 'unknown'}"


def _machine_record_path(report: Report) -> pathlib.Path:
    shared = _runtime_value(report, "skills.shared-path")
    if shared is None:
        raise ValueError("skills.shared-path must pass before record generation")
    return pathlib.Path(shared) / _machine_name() / "SKILL.md"


def _machine_record(
    report: Report, context: Context, wizard_path: pathlib.Path | None
) -> MachineRecord:
    machine_name = _machine_name()
    container = pathlib.Path("/.dockerenv").exists() or pathlib.Path("/run/.containerenv").exists()
    system = platform.system()
    os_name = system if system in {"Linux", "Darwin", "Windows"} else "other"
    default_shared = context.home / ".agents" / "skills"
    default_xdg = context.home / ".local" / "state"
    default_wizard = context.home / ".config" / "impstack" / "commission-wizard.sh"
    runtimes = (
        RuntimeRecord(
            "Node",
            _executable_path(_runtime_value(report, "runtime.node"), "node"),
            _version("node", context),
        ),
        RuntimeRecord(
            "npx",
            _executable_path(_runtime_value(report, "runtime.npx"), "npx"),
            _version("npx", context),
        ),
        RuntimeRecord(
            "Bun",
            _executable_path(shutil.which("bun", path=context.environment.get("PATH")), "bun"),
            _version("bun", context),
        ),
        RuntimeRecord(
            "Package manager",
            _executable_path(shutil.which("npm", path=context.environment.get("PATH")), "npm"),
            _runtime_version(report, "runtime.package-manager"),
        ),
    )
    harnesses: list[HarnessRecord] = []
    for harness in ("claude", "codex", "opencode"):
        auth = _result(report, f"harness.{harness}.auth")
        canary = _result(report, f"harness.{harness}.canary")
        harnesses.append(
            HarnessRecord(
                harness,
                auth is not None and auth.status is not Status.NOT_APPLICABLE,
                _version(harness, context),
                auth is not None and auth.status is Status.PASS,
                canary.status if canary else None,
            )
        )
    connections = tuple(
        ConnectionRecord(
            result.assertion_id.split(".")[1],
            result.assertion_id.split(".")[2],
            result.status,
            result.message,
        )
        for result in report.results
        if result.assertion_id.startswith("mcp.")
    )
    contract = tuple(
        ContractRecord(
            result.assertion_id,
            result.status,
            result.evidence.command,
            result.message,
        )
        for result in report.results
    )
    wizard_location = _selected_path(
        wizard_path,
        {default_wizard: "$HOME/.config/impstack/commission-wizard.sh"},
        "custom",
    )
    remediations: list[RemediationRecord] = []
    for result in report.results:
        if result.status not in result.remediation_statuses or (
            result.status is Status.NOT_APPLICABLE
            and not result.applicability.remediation_actionable
        ):
            continue
        text = (
            f"Run wizard stage `{result.remediation_text}` from `{wizard_location}`."
            if result.remediation_kind == "wizard" and wizard_path
            else result.remediation_text
        )
        remediations.append(RemediationRecord(result.assertion_id, text))
    return MachineRecord(
        hostname=machine_name.removeprefix("machine-"),
        os_name=os_name,
        os_version=_selected_version(platform.release()),
        container=container,
        shell=_selected_path(
            context.environment.get("SHELL"),
            {
                pathlib.Path(path): path
                for path in (
                    "/bin/bash",
                    "/bin/sh",
                    "/bin/zsh",
                    "/usr/bin/bash",
                    "/usr/bin/fish",
                    "/usr/bin/zsh",
                    "/opt/homebrew/bin/fish",
                    "/opt/homebrew/bin/zsh",
                )
            },
            "unknown",
        ),
        runtimes=runtimes,
        xdg_state_home=_selected_path(
            context.environment.get("XDG_STATE_HOME"),
            {default_xdg: "$HOME/.local/state"},
            "not set",
        ),
        shared_skills=_selected_path(
            _runtime_value(report, "skills.shared-path"),
            {default_shared: "$HOME/.agents/skills"},
            "unavailable",
        ),
        harnesses=tuple(harnesses),
        connections=connections,
        contract=contract,
        remediations=tuple(remediations),
    )


def render_record(record: MachineRecord) -> str:
    lines = [
        "---",
        f"name: machine-{record.hostname}",
        "description: Use for setup, troubleshooting, or provisioning on this machine.",
        "---",
        "",
        f"# Machine {record.hostname}",
        "",
        "## Identity",
        "",
        f"- Hostname: `{record.hostname}`",
        f"- OS: `{record.os_name} {record.os_version}`",
        f"- Container: `{'yes' if record.container else 'no'}`",
        f"- Shell: `{record.shell}`",
        "",
        "## Runtime",
        "",
    ]
    for runtime in record.runtimes:
        lines.append(
            f"- {runtime.name}: `{runtime.path}`. Version: `{runtime.version}`"
        )
    lines.extend(
        [
            f"- XDG state home: `{record.xdg_state_home}`",
            f"- Shared skills: `{record.shared_skills}`",
            "",
            "## Harnesses",
            "",
            "| Harness | Installed | Version | Authenticated | Conventions |",
            "|---|---|---|---|---|",
        ]
    )
    for harness in record.harnesses:
        lines.append(
            f"| {harness.name} | {'yes' if harness.installed else 'no'} | {harness.version} | "
            f"{'yes' if harness.authenticated else 'no'} | "
            f"{harness.conventions.value if harness.conventions else 'unknown'} |"
        )
    lines.extend(["", "## Connections", ""])
    for connection in record.connections:
        lines.append(
            f"- {connection.server} for {connection.harness}: `{connection.status.value}`. "
            f"{connection.message}"
        )
    lines.extend(["", "## Contract", ""])
    for assertion in record.contract:
        lines.append(
            f"- `{assertion.assertion_id}`: `{assertion.status.value}`. "
            f"Command: `{assertion.command}`. {assertion.message}"
        )
    lines.extend(["", "## Remediation", ""])
    if record.remediations:
        for remediation in record.remediations:
            lines.append(f"- `{remediation.assertion_id}`: {remediation.text}")
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
                    'open_url "https://executor.sh"',
                    'say "Sign in, then copy the tenant MCP URL. Input stays hidden."',
                    'ask_secret EXECUTOR_MCP_URL "Executor MCP URL:"',
                    'write_env EXECUTOR_MCP_URL "$EXECUTOR_MCP_URL"',
                    'say "To use the saved value, source $ENV_FILE, then run ./install.sh mcp."',
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


def _load_wizard_template(path: pathlib.Path) -> str:
    if not path.is_file():
        raise ValueError(
            f"wizard template is missing: {path}; install the wizard skill"
        )
    template = path.read_text()
    for helper in WIZARD_HELPERS:
        if re.search(rf"(?m)^{re.escape(helper)}\s*\(\)\s*\{{", template) is None:
            raise ValueError(f"wizard template is missing helper: {helper}")
    return template


def _artifact_plan(artifact: Artifact) -> managed.Plan:
    plan = managed.classify(
        artifact.key, artifact.path, artifact.content, artifact.content, None
    )
    if plan.action == "noop" and artifact.path.stat().st_mode & 0o777 != artifact.mode:
        return managed.Plan(
            plan.key, plan.path, plan.desired, "replace", plan.existing
        )
    return plan


def _write_artifacts(artifacts: Sequence[Artifact], force: bool) -> None:
    paths = tuple(artifact.path.resolve() for artifact in artifacts)
    if len(set(paths)) != len(paths):
        raise ValueError("record and wizard paths must differ")
    plans = tuple(_artifact_plan(artifact) for artifact in artifacts)
    previous_umask = os.umask(0o077)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            protected = tuple(managed.protect(plan) for plan in plans)
    finally:
        os.umask(previous_umask)
    for artifact, protected_plan in zip(artifacts, protected, strict=True):
        if protected_plan.backup_path is not None:
            protected_plan.backup_path.chmod(artifact.mode)
    conflicts = tuple(plan for plan in plans if plan.action == "conflict")
    if conflicts and not force:
        raise ValueError("managed artifact conflict; rerun with --force")
    staged: list[tuple[managed.ProtectedPlan, pathlib.Path]] = []
    try:
        for artifact, protected_plan in zip(artifacts, protected, strict=True):
            if protected_plan.plan.action == "noop":
                continue
            temporary = managed.stage_replacement(protected_plan)
            temporary.chmod(artifact.mode)
            staged.append((protected_plan, temporary))
        for protected_plan, temporary in staged:
            managed.commit(temporary, protected_plan.plan.path)
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)


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
    probe.add_argument("--record", type=pathlib.Path)
    probe.add_argument("--wizard", type=pathlib.Path)
    probe.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    try:
        repo = args.repo.resolve()
        home = args.home.resolve()
        outside_root = home / ".cache" / "impstack" / "commission"
        if outside_root == repo or repo in outside_root.parents:
            raise ValueError("outside-project directory must be outside the repository")
        outside_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=outside_root) as temporary_directory:
            context = _context(args, pathlib.Path(temporary_directory))
            contract_path = args.contract or context.repo / "commission.contract.json"
            report = evaluate(load_contract(contract_path), context)
        if args.action == "check":
            sys.stdout.write(render_report(report, args.format))
        else:
            wizard_path = args.wizard
            record_path = args.record or _machine_record_path(report)
            artifacts: list[Artifact] = []
            if wizard_path:
                shared_result = _result(report, "skills.shared-path")
                if shared_result is None or shared_result.status is not Status.PASS:
                    raise ValueError("skills.shared-path must pass before wizard generation")
                template_path = pathlib.Path(shared_result.evidence.stdout) / "wizard" / "template.sh"
                artifacts.append(
                    Artifact(
                        "wizard",
                        wizard_path,
                        render_wizard(_load_wizard_template(template_path), report).encode(),
                        0o700,
                    )
                )
            artifacts.append(
                Artifact(
                    "record",
                    record_path,
                    render_record(_machine_record(report, context, wizard_path)).encode(),
                    0o600,
                )
            )
            _write_artifacts(artifacts, args.force)
            default_record = home / ".agents" / "skills" / _machine_name() / "SKILL.md"
            record_label = _selected_path(
                record_path,
                {default_record: f"$HOME/.agents/skills/{_machine_name()}/SKILL.md"},
                "custom",
            )
            print(f"record wrote {record_label}")
            if wizard_path:
                default_wizard = home / ".config" / "impstack" / "commission-wizard.sh"
                wizard_label = _selected_path(
                    wizard_path,
                    {default_wizard: "$HOME/.config/impstack/commission-wizard.sh"},
                    "custom",
                )
                print(f"wizard wrote {wizard_label}")
        return 1 if report.failed else 0
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
