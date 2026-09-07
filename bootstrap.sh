#!/usr/bin/env bash
# One-command bootstrap from a bare machine (Linux or macOS).
#   curl -fsSL https://raw.githubusercontent.com/ivankqw/impstack/main/bootstrap.sh | bash
set -euo pipefail

DEST="${IMPSTACK_DIR:-$HOME/impstack}"
REPO="${IMPSTACK_REPO:-https://github.com/ivankqw/impstack.git}"
PSTACK_DIR="${PSTACK_DIR:-$HOME/.local/share/agent-plugins/pstack-claude}"
PSTACK_REPO="${PSTACK_REPO:-https://github.com/michael-denyer/pstack-claude.git}"
PRIVATE="${PRIVATE_CONFIG:-$HOME/agents-cfg-private}"

legacy_basename="agents""-cfg"
legacy_dir="$HOME/$legacy_basename"
new_dir="$HOME/impstack"
if [ -e "$legacy_dir" ] && [ ! -e "$new_dir" ] && [ ! -L "$new_dir" ]; then
  ln -s "$legacy_dir" "$new_dir"
  echo "== linked legacy checkout: $new_dir -> $legacy_dir"
fi

case "$(uname -s)" in Linux|Darwin) ;; *) echo "unsupported OS: $(uname -s)" >&2; exit 1;; esac
for c in git python3; do command -v "$c" >/dev/null || { echo "missing prerequisite: $c" >&2; exit 1; }; done

if [ -e "$DEST/.git" ]; then
  echo "== updating $DEST"
  git -C "$DEST" pull --ff-only
else
  echo "== cloning into $DEST"
  git clone --depth 1 "$REPO" "$DEST"
fi

PSTACK_REVISION="$(sed -n '1p' "$DEST/pstack-revision.txt")"
SHARED_SKILLS="$("$DEST/bin/skills-sync" resolve-shared)"
SKILLS_LOCK_FILE="$("$DEST/bin/skills-sync" resolve-lock)"
export SHARED_SKILLS SKILLS_LOCK_FILE
if ! printf '%s\n' "$PSTACK_REVISION" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "invalid pstack revision in $DEST/pstack-revision.txt" >&2
  exit 1
fi
if [ -e "$PSTACK_DIR" ] && [ ! -d "$PSTACK_DIR/.git" ]; then
  echo "pstack path exists but is not a git checkout: $PSTACK_DIR" >&2
  exit 1
fi
fetch_pstack_revision() {
  if git -C "$PSTACK_DIR" fetch --depth 1 origin "$PSTACK_REVISION"; then
    return 0
  fi
  echo "could not fetch pinned pstack revision $PSTACK_REVISION; it may be missing or the remote may restrict direct revision fetches; check $DEST/pstack-revision.txt" >&2
  return 1
}
if [ -d "$PSTACK_DIR/.git" ]; then
  if [ -n "$(git -C "$PSTACK_DIR" status --porcelain)" ]; then
    echo "pstack checkout has local changes; leaving it unchanged: $PSTACK_DIR" >&2
    exit 1
  fi
  echo "== fetching pinned pstack revision"
  fetch_pstack_revision || exit 1
else
  echo "== fetching pinned pstack revision into $PSTACK_DIR"
  mkdir -p "$(dirname "$PSTACK_DIR")"
  git init "$PSTACK_DIR"
  git -C "$PSTACK_DIR" remote add origin "$PSTACK_REPO"
  fetch_pstack_revision || exit 1
fi
if ! git -C "$PSTACK_DIR" cat-file -e "$PSTACK_REVISION^{commit}" 2>/dev/null; then
  echo "pstack revision is missing after fetch: $PSTACK_REVISION" >&2
  exit 1
fi
git -C "$PSTACK_DIR" checkout --detach "$PSTACK_REVISION"

python3 "$DEST/scripts/skill_metadata.py" preflight-pstack \
  "$PSTACK_DIR" "$DEST/pstack-revision.txt"

set +e
"$DEST/install.sh" "$@"
install_rc=$?
set -e

if [ "$install_rc" -ne 0 ]; then
  exit "$install_rc"
fi
if ! python3 "$DEST/scripts/skill_metadata.py" require-skill-name \
  "$SHARED_SKILLS/herdr/SKILL.md" herdr; then
  echo "Herdr restore failed: invalid $SHARED_SKILLS/herdr/SKILL.md" >&2
  exit 1
fi

case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
  echo; echo "!! add this to your shell profile:"; echo '   export PATH="$HOME/.local/bin:$PATH"';;
esac
echo; echo "== done. Verify with the check in $DEST/AGENTS.md"
