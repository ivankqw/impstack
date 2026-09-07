# Maintaining this repo

For an agent asked to change this setup. `AGENTS.md` covers installing it. This file covers editing
it without breaking it.

Two rules run through everything below.

**Verify, do not assume.** Every recipe here ends in a check you can run. A broken agent config
fails quietly: the file sits on disk, nothing loads it, and no error appears.

**Do not copy upstream skills into this repo.** Most skills come from other people's repos and are
managed by `npx skills`. A copy pins them to one commit and cuts them off from updates.

## Add a skill I wrote

1. Write `skills/<name>/SKILL.md`. Frontmatter needs `name` and `description`.
2. Run `./install.sh`. It links per item, so a new folder needs the re-run.
3. Check the skill appears, then invoke it once.

The `description` decides when an agent reaches for the skill. Lead it with the trigger, not the
subject.

## Add a third-party skill

```bash
npx skills add <owner>/<repo>
./install.sh                    # Codex discovers it; Claude receives a link and checks metadata
```

Then record it, so a fresh machine gets it too. Normalize the CLI lockfile and read the diff:

```bash
cd ~/impstack
bin/skills-sync normalize
git diff skills-catalog.json
```

Add intentionally untracked skill names to `skills-ignore.txt`. Use one glob per line. The
normalizer excludes matching lockfile entries, and the checker ignores matching installed folders.
The larksuite skills stay outside the committed catalog because they are managed separately.
The skills CLI normally writes its lockfile to `~/.agents/.skill-lock.json`. `XDG_STATE_HOME` changes
that location. `SKILLS_LOCK_FILE` overrides both locations.
`SHARED_SKILLS` overrides the default `~/.agents/skills` directory. Keep all path resolution in
`bin/skills-sync`. Export the resolved values before you call child commands.
Keep instruction-file writes in `scripts/managed_instructions.py`. Its checksum covers all bytes
after the provenance marker. Do not remove the preflight plan across both managed files.
Keep backup retention at five files per managed target.
The normalizer preserves catalog entries that are absent from the current machine. It prints each
proposed removal. Review those names before you run `bin/skills-sync normalize --allow-removals`.

`install.sh` tries every missing catalog skill. A failed third-party restore prints a warning, but
the installer continues to link the agent configuration.

If an imported skill must stay explicit-use-only, add or update its description override in
`scripts/skill_metadata.py`. `install.sh` applies and checks those overrides in `~/.agents/skills`
after each restore or update, so Codex sees the constrained triggers.

## Let a skill invoke another skill

Upstream marks some skills `disable-model-invocation: true`, which reserves them for the human. A
skill cannot call them and the runtime refuses to let you rebuild their workflow.

`skillOverrides` cannot lift the flag. The harness locks the `on` and `name-only` states whenever the
frontmatter sets it. The flag has to leave the file.

Add the skill name to `skills-unlock.txt` and run `./install.sh`, which strips the flag in
`~/.agents/skills`. Leave a skill locked when it only makes sense from a human.

**`npx skills update` restores the flag.** Run `./bin/skills-update` for updates. It runs the update,
then reapplies checks and restores `skills-unlock.txt`.

## Change a convention

Edit `conventions/AGENTS.md`. Claude Code picks it up on the next turn through the `@import`. Codex
reads a generated copy, so run `./install.sh` or Codex keeps the old text.

Check it loaded:

```bash
cd /tmp && claude -p "Do not use tools. If your instructions contain '<a phrase you just wrote>',
write LOADED, else write MISSING."
```

Keep the file under 200 lines. Past that, the harness docs say instructions start getting ignored,
so trim before you add. Ask of each line: would removing it cause a mistake? If not, cut it.

## Add a hook

Put the script in `hooks/` and run `./install.sh`. Register it in `~/.claude/settings.json`, which
this repo does not track; `settings/settings.template.json` shows the shape.

Keep hooks advisory. A blocking hook that fires on work you consider fine gets switched off, and then
it protects nothing. Feed evidence into the turn and let the model decide.

The install links each hook into both harness directories. It preserves a non-symlink user file.
Register Codex hooks with `settings/codex.config.template.toml`. The install never edits the config.

Test a hook by piping the event JSON into it:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git push origin x"}}' | python3 hooks/<name>.py
```

## Add an agent

Write `agents/<name>.md` with `name`, `description`, `model`, and `effort`. Run `./install.sh`.

`effort` works only in the agent file. No dispatch-time parameter sets it, so an agent without it
runs at whatever the session is using.

## Update pstack

Use a clean pstack checkout. Fetch and examine the upstream revision before you record it.

```bash
git -C ~/.local/share/agent-plugins/pstack-claude fetch origin
git -C ~/.local/share/agent-plugins/pstack-claude show <revision>
printf '%s\n' <full-commit-id> > pstack-revision.txt
./bootstrap.sh
```

Bootstrap stops when the checkout has local changes. It also stops when the revision is missing.
Install rejects a checkout at a different revision.

Do not add pstack to `skills-catalog.json`. Do not copy pstack skills into this repo. The pinned plugin
checkout supplies its skills and prompt stubs.

Update `configs/pstack-codex.md` only with confirmed Codex model slugs. The install appends this file
to generated Codex instructions because Codex does not support Claude `@imports`.

## Maintain the plugin manifests

The root manifests follow the [Agent Plugins 1.0.0 specification](https://github.com/agentplugins/agent-plugins-spec/blob/main/spec/1.0.0.md).
The portable `mcp.json` mirrors fixed URLs from `mcp/servers.json`. It omits the executor because the
portable schema does not expand environment variables in remote URLs.

Claude hooks remain settings-wired. The Claude plugin manifest must not declare hooks unless this
repository adds `hooks/hooks.json`.

## What never goes in this repo

- Credentials of any kind. `mcp/servers.json` holds names and URLs; keys come from the environment.
  A URL that names a tenant or a person is declared as `url_env` and also comes from the environment.
- `~/.claude.json`. It mixes machine state with an API key.
- Anything naming an employer, a host, or a person. That belongs in the private layer at
  `~/agents-cfg-private`.
- Transcripts, job scratch, and `history.jsonl`.

## Traps that cost time

- **A prose reference loads nothing.** Naming another file in `CLAUDE.md` does not pull it in. Only
  `@import` does. A whole conventions file sat unread for months this way.
- **`git commit -m` with a quoted phrase inside the message fails**, and the `git push` afterwards
  still prints success. Write the message to a temp file and use `-F`.
- **`grep -c` prints `0` and exits `1`.** A `|| echo 0` fallback then doubles the value and every
  comparison after it is wrong.
- **`skillOverrides` matches by name.** When upstream renames a skill, an `off` override stops
  covering it and the skill comes back unannounced.
- **The skills CLI lockfile contains machine state.** Commit only the stable fields from
  `bin/skills-sync normalize`.
- **BSD and GNU differ.** `date -Iseconds`, `readlink -f`, `stat -c` and `sed -i` all behave
  differently on macOS. Prefer plain format strings.
- **Harness direction is not symmetric.** The default config needs Claude Code to dispatch the
  Sonnet reviewer. Select `single-vendor` when Claude is unavailable.

## Before you say it works

Run the canonical unit test command:

```bash
python3 -m unittest discover -s tests
```

Do not use `python3 -m unittest -v` alone. It can report zero tests from this layout.

Install into a throwaway `HOME` and look at what appears:

```bash
SB=$(mktemp -d); mkdir -p "$SB/home/.local/share/agent-plugins"
git clone --no-hardlinks ~/.local/share/agent-plugins/pstack-claude \
  "$SB/home/.local/share/agent-plugins/pstack-claude"
env HOME="$SB/home" PRIVATE_CONFIG="$SB/none" \
  PSTACK_DIR="$SB/home/.local/share/agent-plugins/pstack-claude" ./install.sh
find "$SB/home" -maxdepth 3 \( -type l -o -type f \)
rm -rf "$SB"
```

Then run the canary from the convention section above. Paste the real output.
