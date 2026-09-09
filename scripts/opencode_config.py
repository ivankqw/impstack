#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import stat
import sys
import tempfile
from collections.abc import Callable
from typing import Any

try:
    from scripts import user_state_paths
except ModuleNotFoundError:
    import user_state_paths


class OpenCodeConfigError(ValueError):
    pass


def config_root(home: pathlib.Path, environment: dict[str, str]) -> pathlib.Path:
    home = home.resolve()
    configured = environment.get("XDG_CONFIG_HOME") or home / ".config"
    try:
        return user_state_paths.resolve(configured, home) / "opencode"
    except ValueError as error:
        raise OpenCodeConfigError(f"invalid OpenCode config path: {error}") from None


def reject_constant(value: str) -> None:
    raise OpenCodeConfigError(f"invalid JSON constant {value}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OpenCodeConfigError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_mapping(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as error:
        raise OpenCodeConfigError(f"could not read {label}: {path}: {error}") from None
    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, OpenCodeConfigError) as error:
        raise OpenCodeConfigError(f"invalid {label}: {path}: {error}") from None
    if not isinstance(value, dict):
        raise OpenCodeConfigError(f"invalid {label}: {path}: root must be an object")
    return value


def write_mapping_if_changed(path: pathlib.Path, value: dict[str, Any]) -> bool:
    desired = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        existing = None
        mode = 0o600
    except OSError as error:
        raise OpenCodeConfigError(f"could not read OpenCode config: {path}: {error}") from None
    else:
        if existing == desired:
            print(f"  unchanged OpenCode config: {path}")
            return False
        mode = stat.S_IMODE(path.stat().st_mode)

    temporary: pathlib.Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as output:
            temporary = pathlib.Path(output.name)
            os.fchmod(output.fileno(), mode)
            output.write(desired)
        os.replace(temporary, path)
    except OSError as error:
        raise OpenCodeConfigError(f"could not write OpenCode config: {path}: {error}") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    print(f"  configured OpenCode: {path}")
    return True


def update_config(
    home: pathlib.Path,
    environment: dict[str, str],
    transform: Callable[[dict[str, Any]], None],
) -> None:
    path = config_root(home, environment) / "opencode.json"
    config = load_mapping(path, "OpenCode config")
    transform(config)
    write_mapping_if_changed(path, config)


def add_instructions(config: dict[str, Any], instructions: pathlib.Path) -> None:
    existing = config.get("instructions", [])
    if not isinstance(existing, list) or not all(isinstance(item, str) for item in existing):
        raise OpenCodeConfigError("invalid OpenCode config: instructions must be an array of strings")
    target_path = instructions.resolve()
    if not target_path.is_file():
        raise OpenCodeConfigError(f"OpenCode instruction file is missing: {target_path}")
    target = str(target_path)
    if target not in existing:
        config["instructions"] = [*existing, target]


def environment_name(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
        raise OpenCodeConfigError(f"invalid MCP catalog: {field} must name an environment variable")
    return value


def render_mcp_servers(
    catalog: dict[str, Any], environment: dict[str, str]
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    servers = catalog.get("servers")
    if not isinstance(servers, list):
        raise OpenCodeConfigError("invalid MCP catalog: servers must be an array")
    names: set[str] = set()
    rendered: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(servers):
        if not isinstance(raw, dict):
            raise OpenCodeConfigError(f"invalid MCP catalog: servers[{index}] must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise OpenCodeConfigError(f"invalid MCP catalog: servers[{index}] has an invalid name")
        names.add(name)
        has_url = "url" in raw
        has_url_env = "url_env" in raw
        if has_url == has_url_env:
            raise OpenCodeConfigError(
                f"invalid MCP catalog: {name} must set exactly one of url or url_env"
            )
        if has_url:
            url = raw["url"]
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                raise OpenCodeConfigError(f"invalid MCP catalog: {name} has an invalid url")
        else:
            url_env = environment_name(raw["url_env"], f"{name}.url_env")
            if not environment.get(url_env):
                continue
            url = f"{{env:{url_env}}}"
        entry: dict[str, Any] = {"type": "remote", "url": url}
        header_env = raw.get("header_env")
        header_name = raw.get("header_name")
        if header_env is not None or header_name is not None:
            env_name = environment_name(header_env, f"{name}.header_env")
            if not isinstance(header_name, str) or not header_name:
                raise OpenCodeConfigError(
                    f"invalid MCP catalog: {name}.header_name must be a non-empty string"
                )
            entry["headers"] = {header_name: f"{{env:{env_name}}}"}
        rendered[name] = entry
    return names, rendered


def add_mcp_servers(
    config: dict[str, Any], catalog: dict[str, Any], environment: dict[str, str]
) -> None:
    names, rendered = render_mcp_servers(catalog, environment)
    existing = config.get("mcp", {})
    if not isinstance(existing, dict):
        raise OpenCodeConfigError("invalid OpenCode config: mcp must be an object")
    merged = {name: value for name, value in existing.items() if name not in names}
    merged.update(rendered)
    config["mcp"] = merged


def frontmatter_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    for line in lines:
        if line.startswith((" ", "\t")):
            if not blocks:
                raise OpenCodeConfigError("invalid reviewer frontmatter: orphan continuation")
            blocks[-1][1].append(line)
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):", line)
        if match is None:
            raise OpenCodeConfigError(f"invalid reviewer frontmatter line: {line.rstrip()!r}")
        key = match.group(1)
        if any(existing == key for existing, _ in blocks):
            raise OpenCodeConfigError(f"invalid reviewer frontmatter: duplicate key {key!r}")
        blocks.append((key, [line]))
    return blocks


def render_reviewer(source: pathlib.Path) -> bytes:
    try:
        text = source.read_text()
    except (OSError, UnicodeDecodeError) as error:
        raise OpenCodeConfigError(f"could not read reviewer source: {source}: {error}") from None
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise OpenCodeConfigError("invalid reviewer frontmatter: missing opening boundary")
    try:
        closing = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        raise OpenCodeConfigError("invalid reviewer frontmatter: missing closing boundary") from None
    blocks = frontmatter_blocks(lines[1:closing])
    keys = {key for key, _ in blocks}
    if "description" not in keys:
        raise OpenCodeConfigError("invalid reviewer frontmatter: missing description")
    kept = [block for block in blocks if block[0] not in {"name", "model", "effort", "mode", "permission"}]
    frontmatter = [line for _, block in kept for line in block]
    frontmatter.extend(("mode: subagent\n", "permission:\n", "  edit: deny\n"))
    return ("---\n" + "".join(frontmatter) + "---\n" + "".join(lines[closing + 1 :])).encode()


def write_bytes_if_changed(path: pathlib.Path, desired: bytes) -> bool:
    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        existing = None
    except OSError as error:
        raise OpenCodeConfigError(f"could not read OpenCode file: {path}: {error}") from None
    if existing == desired:
        print(f"  unchanged OpenCode file: {path}")
        return False
    temporary: pathlib.Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as output:
            temporary = pathlib.Path(output.name)
            output.write(desired)
        os.replace(temporary, path)
    except OSError as error:
        raise OpenCodeConfigError(f"could not write OpenCode file: {path}: {error}") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    print(f"  installed OpenCode file: {path}")
    return True


def link_skills(home: pathlib.Path, environment: dict[str, str], shared: pathlib.Path) -> None:
    home = home.resolve()
    shared = user_state_paths.resolve(shared, home)
    if not shared.is_dir():
        raise OpenCodeConfigError(f"shared skills directory is missing: {shared}")
    if shared == (home / ".agents" / "skills").resolve():
        print(f"  OpenCode uses shared skills natively: {shared}")
        return
    destination = config_root(home, environment) / "skills"
    if destination.is_symlink():
        if destination.resolve() == shared:
            print(f"  unchanged OpenCode skills link: {destination}")
            return
        destination.unlink()
    elif destination.exists():
        raise OpenCodeConfigError(
            f"OpenCode skills path exists and is not a symlink: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(shared, target_is_directory=True)
    print(f"  linked OpenCode skills: {destination} -> {shared}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=pathlib.Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    instructions = subparsers.add_parser("instructions")
    instructions.add_argument("--source", type=pathlib.Path, required=True)
    skills = subparsers.add_parser("skills")
    skills.add_argument("--shared", type=pathlib.Path, required=True)
    reviewer = subparsers.add_parser("reviewer")
    reviewer.add_argument("--source", type=pathlib.Path, required=True)
    mcp = subparsers.add_parser("mcp")
    mcp.add_argument("--servers", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    environment = dict(os.environ)

    if args.command == "instructions":
        update_config(
            args.home,
            environment,
            lambda config: add_instructions(config, args.source),
        )
    elif args.command == "skills":
        link_skills(args.home, environment, args.shared)
    elif args.command == "reviewer":
        destination = config_root(args.home, environment) / "agents" / "reviewer.md"
        write_bytes_if_changed(destination, render_reviewer(args.source))
    elif args.command == "mcp":
        catalog = load_mapping(args.servers, "MCP catalog")
        update_config(
            args.home,
            environment,
            lambda config: add_mcp_servers(config, catalog, environment),
        )
    return 0


if __name__ == "__main__":
    try:
        exit_code = main(sys.argv[1:])
    except (OpenCodeConfigError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)
