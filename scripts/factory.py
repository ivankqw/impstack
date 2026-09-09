#!/usr/bin/env python3

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import pathlib
import sys
from collections.abc import Mapping, Sequence
from typing import Any


ROLE_NAMES = ("orchestrator", "implementer", "reviewer")
HARNESSES = {"claude-code", "codex-cli", "codex-app", "opencode"}
TERMINAL_HARNESSES = {"claude-code", "codex-cli", "opencode"}
PROFILE_TRANSPORTS = {"native-codex-app", "herdr-cli"}
ASSIGNMENT_TRANSPORTS = {"native-codex-app", "herdr-cli", "hybrid"}
PROFILE_OPTION_KEYS = {
    "fresh_context",
    "cross_vendor",
    "parallel",
    "harness_options",
    "provider_options",
}
RECIPE_INVARIANTS = {
    "review_independence",
    "isolated_workspace",
    "recorded_evidence",
    "operator_release",
}
BRIEF_FIELDS = (
    "version",
    "kind",
    "task_id",
    "objective",
    "worktree",
    "branch",
    "base_commit",
    "acceptance",
    "checks",
    "constraints",
    "recipe",
    "assignment",
    "transport",
    "roles",
)
RESULT_FIELDS = (
    "version",
    "kind",
    "task_id",
    "worktree",
    "base_commit",
    "actual_commit",
    "status",
    "evidence",
    "unresolved_work",
    "artifacts",
    "recipe",
    "assignment",
    "transport",
    "roles",
)
RESULT_STATUSES = {"success", "failed", "blocked", "incomplete"}


class FactoryError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Profile:
    name: str
    harness: str
    transport: str
    provider: str
    model: str
    options: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class Step:
    name: str
    role: str


@dataclasses.dataclass(frozen=True)
class Recipe:
    name: str
    roles: tuple[str, ...]
    steps: tuple[Step, ...]
    invariants: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Assignment:
    name: str
    recipe: str
    transport: str
    roles: Mapping[str, str]
    modules: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class FactoryConfig:
    name: str
    profiles: Mapping[str, Profile]
    recipes: Mapping[str, Recipe]
    assignments: Mapping[str, Assignment]
    modules: Mapping[str, Mapping[str, str]]


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FactoryError(f"{label} must be an object")
    return value


def _keys(
    value: Mapping[str, Any],
    label: str,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> None:
    allowed = set(required) | set(optional)
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FactoryError(f"{label} has unknown key(s): {', '.join(unknown)}")
    missing = [key for key in required if key not in value]
    if missing:
        raise FactoryError(f"{label} is missing key(s): {', '.join(missing)}")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FactoryError(f"{label} must be a non-empty string")
    return value


def _string_list(value: object, label: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise FactoryError(f"{label} must be a non-empty array of strings")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise FactoryError(f"{label} must contain only non-empty strings")
    if len(set(value)) != len(value):
        raise FactoryError(f"{label} must not contain duplicates")
    return tuple(value)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FactoryError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise FactoryError(f"non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise FactoryError(f"non-finite JSON number: {value}")
    return number


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (OSError, UnicodeError) as error:
        raise FactoryError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise FactoryError(f"invalid JSON in {path}: {error}") from error
    return _object(value, str(path))


def _parse_profile(name: str, raw: object) -> Profile:
    profile = _object(raw, f"profile {name}")
    _keys(profile, f"profile {name}", ("harness", "transport", "provider", "model", "options"))
    harness = _string(profile["harness"], f"profile {name}.harness")
    if harness not in HARNESSES:
        raise FactoryError(f"profile {name}.harness is unsupported: {harness}")
    transport = _string(profile["transport"], f"profile {name}.transport")
    if transport not in PROFILE_TRANSPORTS:
        raise FactoryError(f"profile {name}.transport is unsupported: {transport}")
    if transport == "native-codex-app" and harness != "codex-app":
        raise FactoryError(
            f"profile {name}.transport native-codex-app requires harness codex-app"
        )
    if transport == "herdr-cli" and harness not in TERMINAL_HARNESSES:
        raise FactoryError(
            f"profile {name}.transport herdr-cli requires a terminal harness"
        )
    provider = _string(profile["provider"], f"profile {name}.provider")
    model = _string(profile["model"], f"profile {name}.model")
    for key, value in (("provider", provider), ("model", model)):
        if value != value.strip():
            raise FactoryError(f"profile {name}.{key} must not have surrounding whitespace")
    options = _object(profile["options"], f"profile {name}.options")
    unknown = sorted(set(options) - PROFILE_OPTION_KEYS)
    if unknown:
        raise FactoryError(
            f"profile {name}.options has unknown key(s): {', '.join(unknown)}"
        )
    for key in ("fresh_context", "cross_vendor", "parallel"):
        if key in options and not isinstance(options[key], bool):
            raise FactoryError(f"profile {name}.options.{key} must be boolean")
    for key in ("harness_options", "provider_options"):
        if key in options:
            _object(options[key], f"profile {name}.options.{key}")
    return Profile(name, harness, transport, provider, model, dict(options))


def _parse_recipe(name: str, raw: object) -> Recipe:
    recipe = _object(raw, f"recipe {name}")
    _keys(recipe, f"recipe {name}", ("roles", "steps", "invariants"))
    roles = _string_list(recipe["roles"], f"recipe {name}.roles")
    if set(roles) != set(ROLE_NAMES):
        raise FactoryError(
            f"recipe {name}.roles must contain exactly: {', '.join(ROLE_NAMES)}"
        )
    raw_steps = recipe["steps"]
    if not isinstance(raw_steps, list) or not raw_steps:
        raise FactoryError(f"recipe {name}.steps must be a non-empty array")
    steps: list[Step] = []
    step_names: set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        step = _object(raw_step, f"recipe {name}.steps[{index}]")
        _keys(step, f"recipe {name}.steps[{index}]", ("id", "role"))
        step_id = _string(step["id"], f"recipe {name}.steps[{index}].id")
        role = _string(step["role"], f"recipe {name}.steps[{index}].role")
        if step_id in step_names:
            raise FactoryError(f"recipe {name}.steps has duplicate id: {step_id}")
        if role not in roles:
            raise FactoryError(f"recipe {name}.steps[{index}] references unknown role: {role}")
        step_names.add(step_id)
        steps.append(Step(step_id, role))
    step_roles = [step.role for step in steps]
    missing_roles = sorted(set(roles) - set(step_roles))
    if missing_roles:
        raise FactoryError(f"recipe {name}.steps omits role(s): {', '.join(missing_roles)}")
    last_implementation = max(index for index, role in enumerate(step_roles) if role == "implementer")
    if "reviewer" not in step_roles[last_implementation + 1:]:
        raise FactoryError(f"recipe {name}.steps requires review after the final implementation")
    invariants = _string_list(recipe["invariants"], f"recipe {name}.invariants")
    missing = sorted(RECIPE_INVARIANTS - set(invariants))
    if missing:
        raise FactoryError(
            f"recipe {name}.invariants is missing: {', '.join(missing)}"
        )
    return Recipe(name, roles, tuple(steps), invariants)


def _parse_modules(raw: object) -> dict[str, Mapping[str, str]]:
    modules = _object(raw, "modules")
    _keys(modules, "modules", ("optional",))
    optional = modules["optional"]
    if not isinstance(optional, list):
        raise FactoryError("modules.optional must be an array")
    parsed: dict[str, Mapping[str, str]] = {}
    for index, raw_module in enumerate(optional):
        module = _object(raw_module, f"modules.optional[{index}]")
        _keys(module, f"modules.optional[{index}]", ("name", "description"))
        name = _string(module["name"], f"modules.optional[{index}].name")
        description = _string(
            module["description"], f"modules.optional[{index}].description"
        )
        if name in parsed:
            raise FactoryError(f"modules.optional has duplicate name: {name}")
        parsed[name] = {"name": name, "description": description}
    return parsed


def _parse_assignment(
    name: str,
    raw: object,
    profiles: Mapping[str, Profile],
    recipes: Mapping[str, Recipe],
    modules: Mapping[str, Mapping[str, str]],
) -> Assignment:
    assignment = _object(raw, f"assignment {name}")
    _keys(assignment, f"assignment {name}", ("recipe", "transport", "roles"), ("modules",))
    recipe_name = _string(assignment["recipe"], f"assignment {name}.recipe")
    if recipe_name not in recipes:
        raise FactoryError(f"assignment {name} references unknown recipe: {recipe_name}")
    transport = _string(assignment["transport"], f"assignment {name}.transport")
    if transport not in ASSIGNMENT_TRANSPORTS:
        raise FactoryError(f"assignment {name}.transport is unsupported: {transport}")
    role_refs = _object(assignment["roles"], f"assignment {name}.roles")
    recipe_roles = recipes[recipe_name].roles
    if set(role_refs) != set(recipe_roles):
        raise FactoryError(
            f"assignment {name}.roles must contain exactly: {', '.join(recipe_roles)}"
        )
    resolved_roles: dict[str, str] = {}
    for role in recipe_roles:
        profile_name = _string(role_refs[role], f"assignment {name}.roles.{role}")
        if profile_name not in profiles:
            raise FactoryError(
                f"assignment {name}.roles.{role} references unknown profile: {profile_name}"
            )
        resolved_roles[role] = profile_name
    selected_modules = ()
    if "modules" in assignment:
        selected_modules = _string_list(
            assignment["modules"], f"assignment {name}.modules", nonempty=False
        )
        unknown_modules = sorted(set(selected_modules) - set(modules))
        if unknown_modules:
            raise FactoryError(
                f"assignment {name}.modules references unknown module(s): "
                + ", ".join(unknown_modules)
            )
    profile_transports = {profiles[profile].transport for profile in resolved_roles.values()}
    selected_profiles = [profiles[profile_name] for profile_name in resolved_roles.values()]
    if transport == "native-codex-app" and profile_transports != {"native-codex-app"}:
        raise FactoryError(
            f"assignment {name} requires native-codex-app profiles for every role"
        )
    if transport == "native-codex-app" and any(
        profile.harness != "codex-app" for profile in selected_profiles
    ):
        raise FactoryError("native-codex-app transport requires codex-app profiles")
    if transport == "herdr-cli" and profile_transports != {"herdr-cli"}:
        raise FactoryError(f"assignment {name} requires herdr-cli profiles for every role")
    if transport == "herdr-cli" and any(
        profile.harness not in TERMINAL_HARNESSES for profile in selected_profiles
    ):
        raise FactoryError("herdr-cli transport requires terminal harness profiles")
    if transport == "hybrid":
        if profile_transports != PROFILE_TRANSPORTS:
            raise FactoryError(
                f"assignment {name}.roles must include native-codex-app and herdr-cli profiles"
            )
    implementer = profiles[resolved_roles["implementer"]]
    reviewer = profiles[resolved_roles["reviewer"]]
    if (implementer.provider, implementer.model) == (reviewer.provider, reviewer.model):
        raise FactoryError(
            f"assignment {name} gives implementer and reviewer the same provider/model identity"
        )
    if reviewer.options.get("cross_vendor") is True and reviewer.provider == implementer.provider:
        raise FactoryError(
            f"assignment {name}.roles.reviewer requires a different provider when "
            "options.cross_vendor=true"
        )
    if reviewer.options.get("fresh_context") is not True:
        raise FactoryError(
            f"assignment {name}.roles.reviewer requires options.fresh_context=true"
        )
    return Assignment(name, recipe_name, transport, resolved_roles, selected_modules)


def parse_config(document: Mapping[str, Any]) -> FactoryConfig:
    _keys(document, "config", ("version", "name", "profiles", "recipes", "assignments"), ("modules",))
    if type(document["version"]) is not int or document["version"] != 1:
        raise FactoryError("config.version must be 1")
    config_name = _string(document["name"], "config.name")
    raw_profiles = _object(document["profiles"], "config.profiles")
    if not raw_profiles:
        raise FactoryError("config.profiles must not be empty")
    profiles = {
        _string(name, "profile name"): _parse_profile(name, raw)
        for name, raw in raw_profiles.items()
    }
    raw_recipes = _object(document["recipes"], "config.recipes")
    if not raw_recipes:
        raise FactoryError("config.recipes must not be empty")
    recipes = {
        _string(name, "recipe name"): _parse_recipe(name, raw)
        for name, raw in raw_recipes.items()
    }
    modules = _parse_modules(document["modules"]) if "modules" in document else {}
    raw_assignments = _object(document["assignments"], "config.assignments")
    if not raw_assignments:
        raise FactoryError("config.assignments must not be empty")
    assignments = {
        _string(name, "assignment name"): _parse_assignment(
            name, raw, profiles, recipes, modules
        )
        for name, raw in raw_assignments.items()
    }
    return FactoryConfig(config_name, profiles, recipes, assignments, modules)


def validate_config(path: pathlib.Path) -> FactoryConfig:
    return parse_config(_load_json(path))


def _parse_brief(document: Mapping[str, Any]) -> dict[str, Any]:
    _keys(
        document,
        "brief",
        BRIEF_FIELDS,
        (),
    )
    if type(document["version"]) is not int or document["version"] != 1 or document["kind"] != "factory-brief":
        raise FactoryError("brief must have version 1 and kind factory-brief")
    for key in (
        "task_id",
        "objective",
        "worktree",
        "branch",
        "base_commit",
        "recipe",
        "assignment",
    ):
        _string(document[key], f"brief.{key}")
    _string_list(document["acceptance"], "brief.acceptance")
    _string_list(document["constraints"], "brief.constraints", nonempty=False)
    checks = document["checks"]
    if not isinstance(checks, list) or not checks:
        raise FactoryError("brief.checks must be a non-empty array")
    for index, raw_check in enumerate(checks):
        check = _object(raw_check, f"brief.checks[{index}]")
        _keys(check, f"brief.checks[{index}]", ("command", "purpose"))
        command = check["command"]
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            raise FactoryError(f"brief.checks[{index}].command must be a non-empty string array")
        _string(check["purpose"], f"brief.checks[{index}].purpose")
    _validate_record_binding(document, "brief")
    return dict(document)


def validate_brief(path: pathlib.Path) -> dict[str, Any]:
    return _parse_brief(_load_json(path))


def _validate_record_binding(document: Mapping[str, Any], label: str) -> None:
    for key in ("recipe", "assignment"):
        _string(document[key], f"{label}.{key}")
    transport = _string(document["transport"], f"{label}.transport")
    if transport not in ASSIGNMENT_TRANSPORTS:
        raise FactoryError(f"{label}.transport is unsupported: {transport}")
    roles = _object(document["roles"], f"{label}.roles")
    if set(roles) != set(ROLE_NAMES) or not all(
        isinstance(value, str) and value for value in roles.values()
    ):
        raise FactoryError(f"{label}.roles must map the three required roles to strings")


def _parse_result(document: Mapping[str, Any]) -> dict[str, Any]:
    _keys(document, "result", RESULT_FIELDS)
    if type(document["version"]) is not int or document["version"] != 1 or document["kind"] != "factory-result":
        raise FactoryError("result must have version 1 and kind factory-result")
    for key in (
        "task_id",
        "worktree",
        "base_commit",
    ):
        _string(document[key], f"result.{key}")
    if not isinstance(document["actual_commit"], str):
        raise FactoryError("result.actual_commit must be a string")
    status = _string(document["status"], "result.status")
    if status not in RESULT_STATUSES:
        raise FactoryError(f"result.status is invalid: {status}")
    evidence = document["evidence"]
    if not isinstance(evidence, list):
        raise FactoryError("result.evidence must be an array")
    for index, raw_evidence in enumerate(evidence):
        item = _object(raw_evidence, f"result.evidence[{index}]")
        _keys(item, f"result.evidence[{index}]", ("command", "exit_code", "output"), ("stderr",))
        command = item["command"]
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            raise FactoryError(f"result.evidence[{index}].command must be a non-empty string array")
        if type(item["exit_code"]) is not int:
            raise FactoryError(f"result.evidence[{index}].exit_code must be an integer")
        if not isinstance(item["output"], str):
            raise FactoryError(f"result.evidence[{index}].output must be a string")
        if "stderr" in item and not isinstance(item["stderr"], str):
            raise FactoryError(f"result.evidence[{index}].stderr must be a string")
    unresolved = _string_list(document["unresolved_work"], "result.unresolved_work", nonempty=False)
    artifacts = _string_list(document["artifacts"], "result.artifacts", nonempty=False)
    if status == "success":
        _string(document["actual_commit"], "successful result.actual_commit")
        if unresolved:
            raise FactoryError("successful result must have no unresolved_work")
        if not evidence or any(item["exit_code"] != 0 for item in evidence):
            raise FactoryError("successful result evidence must have exit_code 0")
    if status == "blocked" and not unresolved:
        raise FactoryError("blocked result must list unresolved_work")
    _validate_record_binding(document, "result")
    return dict(document)


def _validate_config_binding(
    record: Mapping[str, Any], config: FactoryConfig, label: str
) -> None:
    assignment_name = record["assignment"]
    if assignment_name not in config.assignments:
        raise FactoryError(f"{label}.assignment is not present in config: {assignment_name}")
    assignment = config.assignments[assignment_name]
    if record["recipe"] != assignment.recipe:
        raise FactoryError(f"{label}.recipe does not match config assignment")
    if record["transport"] != assignment.transport:
        raise FactoryError(f"{label}.transport does not match config assignment")
    if dict(record["roles"]) != dict(assignment.roles):
        raise FactoryError(f"{label}.roles does not match config assignment")


def validate_result(
    path: pathlib.Path,
    brief_path: pathlib.Path | None = None,
    config_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    result = _parse_result(_load_json(path))
    brief = None
    if brief_path is not None:
        brief = validate_brief(brief_path)
        for key in ("task_id", "worktree", "base_commit"):
            if result[key] != brief[key]:
                raise FactoryError(f"result.{key} does not match brief.{key}")
        for key in ("recipe", "assignment", "transport", "roles"):
            if result[key] != brief[key]:
                raise FactoryError(f"result.{key} does not match brief.{key}")
        if result["status"] == "success":
            expected_commands = {tuple(check["command"]) for check in brief["checks"]}
            actual_commands = {tuple(item["command"]) for item in result["evidence"]}
            missing = expected_commands - actual_commands
            if missing:
                raise FactoryError("successful result is missing evidence for a brief check")
    if config_path is not None:
        config = validate_config(config_path)
        _validate_config_binding(result, config, "result")
        if brief is not None:
            _validate_config_binding(brief, config, "brief")
    return result


def _contract(kind: str) -> dict[str, Any]:
    fields = BRIEF_FIELDS if kind == "factory-brief" else RESULT_FIELDS
    return {
        "kind": kind,
        "version": 1,
        "required_fields": list(fields),
        "status_rule": "success requires recorded zero-exit evidence and no unresolved_work"
        if kind == "factory-result"
        else "planned records do not report execution success",
    }


def build_plan(
    config: FactoryConfig,
    assignment_name: str,
    brief: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if assignment_name not in config.assignments:
        raise FactoryError(f"unknown assignment: {assignment_name}")
    assignment = config.assignments[assignment_name]
    recipe = config.recipes[assignment.recipe]
    role_profiles = {
        role: config.profiles[profile_name] for role, profile_name in assignment.roles.items()
    }
    roles = {
        role: {
            "profile": profile.name,
            "harness": profile.harness,
            "transport": profile.transport,
            "provider": profile.provider,
            "model": profile.model,
            "options": dict(profile.options),
        }
        for role, profile in role_profiles.items()
    }
    steps = [
        {
            "id": step.name,
            "role": step.role,
        }
        for step in recipe.steps
    ]
    handoffs = []
    for role in recipe.roles:
        profile = role_profiles[role]
        if profile.transport == "native-codex-app":
            action = "caller-dispatch"
            requirements = [
                "caller supplies the available native Codex app capability",
                "caller supplies session, permission, and worktree handling",
            ]
        elif profile.transport == "herdr-cli":
            action = "herdr-handoff"
            requirements = [
                "caller supplies an installed Herdr command",
                "caller chooses flags supported by the installed Herdr version",
            ]
        handoffs.append(
            {
                "role": role,
                "profile": profile.name,
                "transport": profile.transport,
                "action": action,
                "command": None,
                "requirements": requirements,
            }
        )
    selected_modules = [config.modules[name] for name in assignment.modules]
    return {
        "kind": "factory-plan",
        "version": 1,
        "config": config.name,
        "assignment": assignment.name,
        "recipe": recipe.name,
        "transport": assignment.transport,
        "roles": roles,
        "steps": steps,
        "invariants": list(recipe.invariants),
        "handoffs": handoffs,
        "modules": {
            "optional": selected_modules,
            "installation": "none",
        },
        "brief": dict(brief) if brief is not None else None,
        "contracts": {
            "brief": _contract("factory-brief"),
            "result": _contract("factory-result"),
        },
    }


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


def _format_success(kind: str, path: pathlib.Path, output_format: str, **extra: Any) -> None:
    payload = {"valid": True, "kind": kind, "path": str(path), **extra}
    if output_format == "json":
        _print_json(payload)
    else:
        print(f"valid {kind}: {path}")


def _add_format(parser: argparse.ArgumentParser, default: str = "text") -> None:
    parser.add_argument("--format", choices=("text", "json"), default=default)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and plan Impstack factory handoffs.")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate a factory config")
    validate.add_argument("path", type=pathlib.Path)
    _add_format(validate)

    validate_brief_command = commands.add_parser("validate-brief", help="validate a brief")
    validate_brief_command.add_argument("path", type=pathlib.Path)
    validate_brief_command.add_argument("--config", type=pathlib.Path)
    _add_format(validate_brief_command)

    validate_result_command = commands.add_parser("validate-result", help="validate a result")
    validate_result_command.add_argument("path", type=pathlib.Path)
    validate_result_command.add_argument("--brief", type=pathlib.Path)
    validate_result_command.add_argument("--config", type=pathlib.Path)
    _add_format(validate_result_command)

    plan = commands.add_parser("plan", help="emit a declarative execution handoff")
    plan.add_argument("config", type=pathlib.Path)
    plan.add_argument("--assignment", required=True)
    plan.add_argument("--brief", type=pathlib.Path)
    return parser


def run(args: argparse.Namespace) -> int:
    if args.command == "validate":
        config = validate_config(args.path)
        _format_success("config", args.path, args.format, name=config.name)
        return 0
    if args.command == "validate-brief":
        brief = validate_brief(args.path)
        if args.config is not None:
            _validate_config_binding(brief, validate_config(args.config), "brief")
        _format_success("brief", args.path, args.format)
        return 0
    if args.command == "validate-result":
        validate_result(args.path, args.brief, args.config)
        _format_success("result", args.path, args.format)
        return 0
    config = validate_config(args.config)
    brief = validate_brief(args.brief) if args.brief is not None else None
    if brief is not None:
        _validate_config_binding(brief, config, "brief")
        if brief["assignment"] != args.assignment:
            raise FactoryError("brief.assignment does not match the selected assignment")
    _print_json(build_plan(config, args.assignment, brief))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except FactoryError as error:
        if getattr(args, "format", "text") == "json":
            _print_json({"valid": False, "error": str(error)})
        else:
            print(f"factory: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
