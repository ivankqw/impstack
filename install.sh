#!/usr/bin/env bash
# Install the agent config onto this machine. Idempotent — safe to re-run.
#
# Layers: this repo is the portable method layer. If ~/agents-cfg-private (or
# $PRIVATE_CONFIG) exists it is layered on top. At a new job, clone only this
# repo and the workflows stay identical minus the employer specifics.
set -euo pipefail

INSTALL_STEP_REGISTRY=(
  'preflight|== preflight|install_step_preflight|strict'
  'skills|== skills|install_step_skills|strict'
  'skill-triggers|== constraining explicit-use third-party skill triggers|install_step_constraining|strict'
  'skill-unlock|== unlocking skills listed in skills-unlock.txt|install_step_unlocking|strict'
  'agents-hooks|== agents / hooks|install_step_agents_hooks|strict'
  'bin|== bin|install_step_bin|strict'
  'instructions|== instruction files|install_step_instruction_files|defer'
  'mcp|== mcp servers (keys from env; nothing secret is stored in this repo)|install_step_mcp_servers|strict'
  'codex-settings|== Codex settings|install_step_codex_settings|strict'
  'validate|== validating third-party skill catalog|install_step_validating_catalog|strict'
)

list_install_steps() {
  local entry name banner function_name failure_policy
  for entry in "${INSTALL_STEP_REGISTRY[@]}"; do
    IFS='|' read -r name banner function_name failure_policy <<< "$entry"
    printf '%s\n' "$name"
  done
}

print_install_help() {
  echo "usage: ./install.sh [--no-harness] [--force] [--list|--help|<step>]"
  echo
  echo "A single step always runs preflight first."
  echo
  echo "Valid steps:"
  list_install_steps
}

run_install_step() {
  local entry name banner function_name failure_policy
  entry="$1"
  IFS='|' read -r name banner function_name failure_policy <<< "$entry"
  echo "$banner"
  "$function_name"
}

selected_entry=""
NO_HARNESS=false
FORCE=false
action=""
for argument in "$@"; do
  if [ "$argument" = "--no-harness" ]; then
    NO_HARNESS=true
  elif [ "$argument" = "--force" ]; then
    FORCE=true
  elif [ -n "$action" ]; then
    print_install_help >&2
    exit 2
  else
    action="$argument"
  fi
done
if [ -n "$action" ]; then
  if [ "$action" = "--list" ]; then
    list_install_steps
    exit 0
  fi
  if [ "$action" = "--help" ]; then
    print_install_help
    exit 0
  fi
  for entry in "${INSTALL_STEP_REGISTRY[@]}"; do
    IFS='|' read -r name banner function_name failure_policy <<< "$entry"
    if [ "$name" = "$action" ]; then
      selected_entry="$entry"
      break
    fi
  done
  if [ -z "$selected_entry" ]; then
    echo "unknown install step: $action" >&2
    list_install_steps >&2
    exit 2
  fi
fi

install_step_preflight() {
AC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for c in git python3; do
  command -v "$c" >/dev/null || { echo "missing prerequisite: $c" >&2; exit 1; }
done
case "$(uname -s)" in Linux|Darwin) ;; *) echo "unsupported OS: $(uname -s)" >&2; exit 1;; esac
"$AC/bin/skills-sync" resolve-node >/dev/null
"$AC/bin/skills-sync" resolve-npx >/dev/null
detected_harnesses=()
while IFS= read -r harness; do
  detected_harnesses+=("$harness")
done < <(python3 - <<'PY'
import shutil

for name in ("claude", "codex", "opencode"):
    if shutil.which(name):
        print(name)
PY
)
if [ "${detected_harnesses[0]+present}" != present ]; then
  if [ "$NO_HARNESS" = true ]; then
    echo "  detected harnesses: none (--no-harness)"
  else
    echo "missing harness: install claude, codex, or opencode; or pass --no-harness" >&2
    exit 1
  fi
else
  printf -v harness_list '%s, ' "${detected_harnesses[@]}"
  harness_list="${harness_list%, }"
  echo "  detected harnesses: $harness_list"
fi
PRIVATE="${PRIVATE_CONFIG:-$HOME/agents-cfg-private}"
CLAUDE_DIR="$HOME/.claude"
CODEX_DIR="$HOME/.codex"
SHARED_SKILLS="$("$AC/bin/skills-sync" resolve-shared)"
SKILLS_LOCK_FILE="$("$AC/bin/skills-sync" resolve-lock)"
export SHARED_SKILLS SKILLS_LOCK_FILE
PSTACK_DIR="${PSTACK_DIR:-$HOME/.local/share/agent-plugins/pstack-claude}"
BIN="$HOME/.local/bin"

python3 "$AC/scripts/skill_metadata.py" preflight-pstack "$PSTACK_DIR" "$AC/pstack-revision.txt"
PSTACK_RESOLVED="$(cd "$PSTACK_DIR" && pwd -P)"
PSTACK_SKILLS="$PSTACK_RESOLVED/plugins/pstack/skills"
PSTACK_PROMPTS="$PSTACK_RESOLVED/plugins/pstack/.codex-plugin/prompts"
if ! command -v bun >/dev/null; then
  echo "  ! bun is missing; these commands will not work:"
  echo "  ! $PSTACK_SKILLS/poteto-mode/scripts/watch-pr/watch-pr"
  echo "  ! bun $PSTACK_SKILLS/poteto-mode/scripts/orch/orch.ts"
  echo "  ! install bun from https://bun.sh, then re-run this install"
fi

mkdir -p "$CLAUDE_DIR"/{skills,agents,hooks} "$CODEX_DIR"/{hooks,prompts} "$SHARED_SKILLS" "$BIN"
chmod 700 "$SHARED_SKILLS"

link() { # link <target> <linkname>
  [ -e "$1" ] || return 0
  if [ -L "$2" ] || [ ! -e "$2" ]; then ln -sfn "$1" "$2"
  else echo "  ! not a symlink, leaving alone: $2"; fi
}
}

install_step_skills() {
if ! "$AC/bin/skills-sync" install-missing; then
  echo "  ! some cataloged skills could not be restored; continuing install" >&2
fi
for d in "$AC"/skills/*/; do
  link "${d%/}" "$SHARED_SKILLS/$(basename "$d")"
done
[ -d "$PRIVATE/skills" ] && for d in "$PRIVATE"/skills/*/; do
  link "${d%/}" "$SHARED_SKILLS/$(basename "$d")"
done
python3 - "$SHARED_SKILLS" "$CODEX_DIR/prompts" "$PSTACK_SKILLS" "$PSTACK_PROMPTS" <<'PY'
import os, pathlib, sys

shared = pathlib.Path(sys.argv[1])
prompts = pathlib.Path(sys.argv[2])
skill_root = pathlib.Path(sys.argv[3])
prompt_root = pathlib.Path(sys.argv[4])

def target_of(link):
    target = pathlib.Path(os.readlink(str(link)))
    if not target.is_absolute():
        target = link.parent / target
    return target.resolve(strict=False)

def is_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

def prune(link, root):
    if not link.is_symlink():
        return
    target = target_of(link)
    if is_within(target, root) and not target.exists():
        link.unlink()
        print(f"  remove stale pstack link: {link}")

for entry in shared.iterdir():
    prune(entry, skill_root)
    if entry.is_dir() and not entry.is_symlink():
        prune(entry / entry.name, skill_root)
for entry in prompts.iterdir():
    prune(entry, prompt_root)
PY
for d in "$PSTACK_RESOLVED"/plugins/pstack/skills/*/; do
  name="$(basename "$d")"
  destination="$SHARED_SKILLS/$name"
  if [ -d "$destination" ] && [ ! -L "$destination" ]; then
    link "${d%/}" "$destination/$name"
  else
    link "${d%/}" "$destination"
  fi
done
for f in "$PSTACK_PROMPTS"/*.md; do
  link "$f" "$CODEX_DIR/prompts/$(basename "$f")"
done
}

install_step_constraining() {
python3 "$AC/scripts/skill_metadata.py" apply "$SHARED_SKILLS"
python3 "$AC/scripts/skill_metadata.py" check "$SHARED_SKILLS"

for d in "$SHARED_SKILLS"/*/; do link "${d%/}" "$CLAUDE_DIR/skills/$(basename "$d")"; done
}

install_step_unlocking() {
python3 "$AC/scripts/skill_metadata.py" unlock "$AC/skills-unlock.txt" "$SHARED_SKILLS"
}

install_step_agents_hooks() {
for f in "$AC"/agents/*.md;  do link "$f" "$CLAUDE_DIR/agents/$(basename "$f")"; done
STALE_HOOK="$CLAUDE_DIR/hooks/codex_review_reminder.py"
if [ -L "$STALE_HOOK" ]; then
  rm -f "$STALE_HOOK"
elif [ -e "$STALE_HOOK" ]; then
  echo "  ! not a symlink, leaving alone: $STALE_HOOK"
fi
for f in "$AC"/hooks/*;      do link "$f" "$CLAUDE_DIR/hooks/$(basename "$f")"; done
for f in "$AC"/hooks/*;      do link "$f" "$CODEX_DIR/hooks/$(basename "$f")"; done
}

install_step_bin() {
STALE_DELEGATE="$BIN/delegate"
if [ -L "$STALE_DELEGATE" ]; then
  rm -f "$STALE_DELEGATE"
elif [ -e "$STALE_DELEGATE" ]; then
  echo "  ! not a symlink, leaving alone: $STALE_DELEGATE"
fi
for f in "$AC"/bin/*;        do link "$f" "$BIN/$(basename "$f")"; done
[ -d "$PRIVATE/bin" ] && for f in "$PRIVATE"/bin/*; do link "$f" "$BIN/$(basename "$f")"; done
# A false private-bin test returns non-zero; keep the function successful under set -e.
:
}

install_step_instruction_files() {
# Claude reads CLAUDE.md and expands @imports natively, so edits are live.
link "$AC/conventions/AGENTS.md" "$CLAUDE_DIR/AGENTS.portable.md"
if [ -f "$PRIVATE/AGENTS.md" ]; then
  link "$PRIVATE/AGENTS.md" "$CLAUDE_DIR/AGENTS.private.md"
fi
local instruction_status=0
local -a managed_args
managed_args=(--root "$AC" --home "$HOME" --private "$PRIVATE")
[ "$FORCE" = true ] && managed_args+=(--force)
python3 "$AC/scripts/managed_instructions.py" "${managed_args[@]}" || instruction_status=$?
link "$HOME/AGENTS.md" "$CODEX_DIR/AGENTS.md"
link "$AC/configs/pstack-codex.md" "$CODEX_DIR/pstack-models.md"
return "$instruction_status"
}

install_step_mcp_servers() {
if [ -f "$AC/mcp/servers.json" ]; then
  local -a mcp_args
  mcp_args=("$AC/mcp/servers.json")
  if [ "${detected_harnesses[0]+present}" = present ]; then
    mcp_args+=("${detected_harnesses[@]}")
  fi
  python3 - "${mcp_args[@]}" <<'PY'
import json, os, subprocess, sys

failed = False

def output(result):
    return (result.stderr or result.stdout or f"exit {result.returncode}").strip().splitlines()[-1]

def present(command):
    result = subprocess.run(command, capture_output=True, text=True)
    return result.returncode == 0

def add(name, harness, command, probe):
    global failed
    result = subprocess.run(command, capture_output=True, text=True)
    installed = present(probe)
    if installed:
        state = "registered" if result.returncode == 0 else "already present"
        print(f"  {state} {name} for {harness}")
        return
    detail = output(result)
    if result.returncode == 0:
        detail = "registration command succeeded but the server is absent"
    print(f"  error {name} for {harness}: {detail}", file=sys.stderr)
    failed = True

harnesses = sys.argv[2:]
for s in json.load(open(sys.argv[1]))["servers"]:
    name = s["name"]
    url = os.environ.get(s["url_env"]) if "url_env" in s else s["url"]
    env = s.get("header_env")
    for harness in harnesses:
      label = {"claude": "Claude", "codex": "Codex", "opencode": "OpenCode"}[harness]
      if not url:
        print(f"  skipped {name} for {label}: ${s['url_env']} not set")
        continue
      if harness == "opencode":
        print(f"  unsupported {name} for OpenCode: MCP add is interactive only")
        continue
      if harness == "claude":
        if env and not os.environ.get(env):
            print(f"  authentication required {name} for Claude: ${env} not set")
        else:
            probe = ["claude", "mcp", "get", name]
            if present(probe):
                print(f"  already present {name} for Claude")
                continue
            cmd = ["claude", "mcp", "add", "--scope", "user", "--transport", "http", name, url]
            if env:
                cmd += ["--header", f"{s['header_name']}: {os.environ[env]}"]
            add(name, "Claude", cmd, probe)
      elif harness == "codex":
        cmd = ["codex", "mcp", "add", name, "--url", url]
        if env:
            if s.get("header_name", "").lower() != "authorization":
                print(
                    f"  unsupported {name} for Codex: header {s['header_name']} is not bearer auth"
                )
                continue
            if not os.environ.get(env):
                print(f"  authentication required {name} for Codex: ${env} not set")
                continue
            cmd += ["--bearer-token-env-var", env]
        probe = ["codex", "mcp", "get", name, "--json"]
        if present(probe):
            print(f"  already present {name} for Codex")
            continue
        add(name, "Codex", cmd, probe)
if failed:
    raise SystemExit(1)
PY
fi
}

install_step_codex_settings() {
CODEX_CONFIG="$CODEX_DIR/config.toml"
missing="$(python3 - "$CODEX_CONFIG" "$HOME" "$PSTACK_RESOLVED" <<'PY'
import pathlib, re, sys

path = pathlib.Path(sys.argv[1])
home = sys.argv[2]
pstack_dir = sys.argv[3]
sections = {}
arrays = {}
section = None
hook_parents = {}

def strip_comment(line):
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if char in ("'", '"'):
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            continue
        if char == "#" and quote is None:
            return line[:index]
    return line

if path.is_file():
    for raw in path.read_text().splitlines():
        line = strip_comment(raw).strip()
        if not line:
            continue
        match = re.fullmatch(r"\[\[([^]]+)\]\]", line)
        if match:
            section = match.group(1)
            values = {}
            if section in ("hooks.PreToolUse", "hooks.PostToolUse"):
                hook_parents[section] = values
            elif section == "hooks.PreToolUse.hooks":
                values["_parent"] = hook_parents.get("hooks.PreToolUse", {})
            elif section == "hooks.PostToolUse.hooks":
                values["_parent"] = hook_parents.get("hooks.PostToolUse", {})
            arrays.setdefault(section, []).append(values)
            continue
        match = re.fullmatch(r"\[([^]]+)\]", line)
        if match:
            section = match.group(1)
            values = sections.setdefault(section, {})
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*=\s*(.+)", line)
        if section is not None and match:
            values[match.group(1)] = match.group(2).strip()

missing = []
features = sections.get("features", {})
if features.get("hooks") != "true":
    missing.append("hooks")
if features.get("multi_agent") != "true":
    missing.append("multi_agent")

plugin = sections.get('plugins."pstack@pstack-claude"', {})
if plugin.get("enabled") != "true":
    missing.append("pstack-plugin")

marketplace = sections.get("marketplaces.pstack-claude", {})
source = marketplace.get("source", "")
if len(source) >= 2 and source[0] == source[-1] and source[0] in ("'", '"'):
    source = source[1:-1]
try:
    source_matches = pathlib.Path(source).expanduser().resolve() == pathlib.Path(pstack_dir)
except (OSError, RuntimeError):
    source_matches = False
if marketplace.get("source_type") != '"local"' or not source_matches:
    missing.append("pstack-marketplace")

hook_ok = False
for values in arrays.get("hooks.PreToolUse.hooks", []):
    command = values.get("command", "")
    parent = values.get("_parent", {})
    if (parent.get("matcher") == '"^Bash$"' and values.get("type") == '"command"'
            and home + "/.codex/hooks/review_reminder.py" in command):
        hook_ok = True
if not hook_ok:
    missing.append("review-hook")

cleanup_hook_ok = False
for values in arrays.get("hooks.PostToolUse.hooks", []):
    command = values.get("command", "")
    parent = values.get("_parent", {})
    if (parent.get("matcher") == '"^Bash$"' and values.get("type") == '"command"'
            and home + "/.codex/hooks/cleanup_crew_after_pr.py" in command):
        cleanup_hook_ok = True
if not cleanup_hook_ok:
    missing.append("cleanup-hook")
print(" ".join(missing))
PY
)"
if [ -n "$missing" ]; then
  echo "  ! missing Codex settings: $missing"
  echo "  ! merge $AC/settings/codex.config.template.toml into $CODEX_CONFIG"
  echo "  ! replace HOME_PATH in the template with $HOME"
fi
}

install_step_validating_catalog() {
"$AC/bin/skills-sync" check
}

if [ -z "$action" ]; then
  deferred_status=0
  for entry in "${INSTALL_STEP_REGISTRY[@]}"; do
    IFS='|' read -r name banner function_name failure_policy <<< "$entry"
    if [ "$failure_policy" = "defer" ]; then
      echo "$banner"
      set +e
      (set -e; "$function_name")
      step_status=$?
      set -e
      if [ "$step_status" -ne 0 ]; then
        deferred_status="$step_status"
      fi
    else
      run_install_step "$entry"
    fi
  done
  echo "== done. Merge the settings templates by hand."
  exit "$deferred_status"
else
  if [ "$action" != "preflight" ]; then
    run_install_step "${INSTALL_STEP_REGISTRY[0]}"
  fi
  run_install_step "$selected_entry"
fi
