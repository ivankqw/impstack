# Install impstack

Use this guide to put the portable layer on a fresh Linux or macOS machine. The bootstrap path pins
pstack, restores selected upstream skills, and runs the installer.

## Prepare the machine

Install these commands first:

- `git`
- `python3`
- `bash`
- `node` with `npx`

Install `bun` if you use the pstack `watch-pr` or `orch` tools. Bun's installer also requires
`unzip`; on Debian and Ubuntu, install it with `sudo apt-get install unzip` before running the Bun
installer. `install.sh` warns when `bun` is absent and continues without those tools.

Put `~/.local/bin` on your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add the same line to your shell profile if a new terminal loses the setting.

## Bootstrap the portable layer

Run the remote bootstrap for the shortest setup:

```bash
curl -fsSL https://raw.githubusercontent.com/ivankqw/impstack/main/bootstrap.sh | bash
```

Use a clone when you want to read the scripts before you run them:

```bash
git clone https://github.com/ivankqw/impstack.git ~/impstack
~/impstack/bootstrap.sh
```

The HTTPS form works on a new machine without a GitHub SSH key. Use the SSH remote when that machine
already has a GitHub key configured.

Herdr is optional. Pass `--with-herdr` only when you want to restore its skill:

```bash
~/impstack/bootstrap.sh --with-herdr
```

The default bootstrap does not restore or require Herdr.
`[sourced: bootstrap.sh, install.sh, bin/skills-sync]`

On a machine where you want to install the portable files before installing a harness, pass the
explicit headless option:

```bash
~/impstack/bootstrap.sh --no-harness
```

`bootstrap.sh` refuses unsupported operating systems and missing prerequisites. It refuses a
pstack checkout with local changes. Fix the reported condition and repeat the command.

The bootstrap script uses `~/impstack` unless `IMPSTACK_DIR` names another directory. It clones
the pstack source named by `PSTACK_REPO` and checks out the commit in `pstack-revision.txt`.

## Add a private layer

Keep employer and domain instructions in a separate repository. Put that repository at
`~/agents-cfg-private`, or set `PRIVATE_CONFIG` to its path before bootstrap:

```bash
export PRIVATE_CONFIG="$HOME/path/to/private-agent-config"
~/impstack/bootstrap.sh
```

`install.sh` reads `AGENTS.md`, `skills/`, and `bin/` from the private layer when those paths exist.
Do not put credentials in either repository.

## Merge Claude Code and Codex settings

Claude Code and Codex settings templates remain under operator control.
The installer does not merge these templates. Merge them by hand:

- `settings/settings.template.json` into `~/.claude/settings.json`
- `settings/codex.config.template.toml` into `~/.codex/config.toml`

Replace `HOME_PATH` in the Codex template with your home directory. Restart the harness after you
change its settings.

OpenCode has a different ownership boundary.
The installer manages OpenCode instructions, MCP servers, and permissions in the global config.
`[sourced: install.sh, scripts/opencode_config.py]`

## Verify Claude Code

Run the canary outside any project:

```bash
cd /tmp && claude -p "Do not use tools. If your instructions contain 'A virtue cannot be graded',
write LOADED, else write MISSING."
```

The expected output is:

```text
LOADED
```

`MISSING` means Claude Code did not load `~/.claude/CLAUDE.md`. Run `~/impstack/install.sh` and
repeat the canary.

## Verify Codex

Start a new Codex session from `/tmp`. Ask whether its instructions contain `A virtue cannot be
graded`. Ask for the pstack `bug-fix` model and the `setup-pstack` skill.

Treat a missing phrase, model, or skill as an install failure. Run `~/impstack/install.sh` and read
its Codex settings report. Merge any missing setting from
`settings/codex.config.template.toml`, restart Codex, and repeat the check.

## Verify OpenCode

The installer updates the global OpenCode config when `opencode` is on `PATH`. The default path is
`~/.config/opencode/opencode.json`. `XDG_CONFIG_HOME` replaces `~/.config` when you set it. When
`opencode.jsonc` exists, the installer updates that higher-priority file instead. The write converts
comments and trailing commas in the selected file to JSON. It preserves the order of configuration
and permission rules. When both files exist, it leaves lower-priority permission policies in place.
`[sourced: install.sh, scripts/opencode_config.py, https://opencode.ai/docs/config/]`

The config loads the generated `~/AGENTS.md`. OpenCode reads the default `~/.agents/skills`
directory without another link. If `SHARED_SKILLS` sets another directory, the installer links it
at `~/.config/opencode/skills` or the matching XDG path.
`[sourced: scripts/opencode_config.py, https://opencode.ai/docs/rules/, https://opencode.ai/docs/skills/]`

The global primary agent asks before all actions by default. Existing permission entries override
this wildcard policy.
`[sourced: scripts/opencode_config.py, https://opencode.ai/docs/permissions/]`

Run the canary outside any project:

```bash
cd /tmp
opencode run --format json "Do not use tools. If your instructions contain 'A virtue cannot be graded', write LOADED, else write MISSING."
```

The output contains JSON events. The expected text event has `part.text` set to `LOADED`.
`[sourced: commission.contract.json, scripts/commission.py]`

`MISSING` means OpenCode did not load the generated instructions. Run
`~/impstack/install.sh instructions`, then repeat the canary.

Run `opencode mcp list` to check the installed MCP names. The installer writes remote entries to the
global config because `opencode mcp add` is interactive. It writes environment references instead
of credentials. It omits `executor` when `EXECUTOR_MCP_URL` is not set.
If a lower-priority file still defines `executor`, the adapter disables that inherited entry instead.
`[sourced: install.sh, scripts/opencode_config.py, mcp/servers.json]`

The installer writes the reviewer to the global `agents` directory. The reviewer denies edits. The
renderer keeps the shared review procedure. It drops the legacy Claude preset header, model, effort,
and model-selection guidance.

The generated reviewer inherits its parent OpenCode session's model. The adapter does not read or
select a Factory reviewer profile. It cannot select a different model for that child within an
existing session. Select a different provider and model from the author when the recipe requires
independent review.

The installed reviewer is a subagent. Do not use `opencode run --agent reviewer`. A subagent cannot
run as the primary agent. Do not treat `@reviewer` in a headless `opencode run` prompt as proof of a
reviewer dispatch.

Before a review, inspect the active configuration and agent commands:

```bash
opencode models
opencode debug config
opencode debug agent reviewer
opencode debug skill > skills.json
```

Start a separate session in the reviewed worktree for the reviewer handoff. Set `REVIEW_MODEL` from
the Factory reviewer profile:

```bash
REVIEW_MODEL='provider/model-id'
opencode --model "$REVIEW_MODEL"
```

Do not reuse the author's session when its model conflicts with the recipe's independence requirement.
In the new interactive session, use `@reviewer`. You can also ask the primary agent: "Delegate to the reviewer
subagent through the task tool. Do not review it yourself. Review origin/main...HEAD. Run the
required checks and cite each command and output."

Approve the task only after the requested subagent and model match the Factory plan. Enter the child
session. Confirm its recorded model, task event, and review evidence before you accept its verdict.
The natural-language request does not prove a task dispatch. When the default `ask` rule blocks the
task, approve it in the interactive session. Use a scoped operator permission for headless work only
after you verify the subagent target. Do not enable global automatic approval.

`[sourced: agents/reviewer.md, scripts/opencode_config.py, https://opencode.ai/docs/agents/, https://opencode.ai/docs/cli/]`

## Try Hermes Agent experimentally

Hermes support is experimental. `bootstrap.sh` and `install.sh` do not configure Hermes.

1. Install Hermes and select a model with `hermes model`. Follow the
   [Hermes quickstart](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/getting-started/quickstart.md).
2. Use the project `AGENTS.md`. Do not add a `HERMES.md`. Hermes reads `AGENTS.md` when no
   higher-priority Hermes context file exists. See the
   [Hermes context-file documentation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/context-files.md).
3. Link the own and upstream skill directories from their recorded sources into
   `~/.hermes/skills`. Do not copy them. Use `skills-catalog.json` and `pstack-revision.txt` as the
   source records.
4. Generate `mcp_servers` entries in `~/.hermes/config.yaml` from `mcp/servers.json`. Keep secrets in
   their named environment variables. See the
   [Hermes MCP documentation](https://github.com/NousResearch/hermes-agent/blob/main/skills/autonomous-ai-agents/hermes-agent/references/native-mcp.md).
5. Start Hermes outside a project. Ask whether its instructions contain `A virtue cannot be graded`.
   Ask it to list one linked skill and one configured MCP server. Treat any missing item as an
   experimental setup failure.

Do not use `hermes import-agent claude-code` unless you prove that it preserves source links.

## Update the setup

Sync the portable layer and upstream skills, then refresh the generated files and links:

```bash
cd ~/impstack
bin/skills-sync run
./install.sh
```

`bin/skills-sync run` pulls the repository, restores missing catalogued skills, and updates installed
upstream skills. It normalizes and validates `skills-catalog.json`, commits a change, and pushes it.
If a concurrent sync wins the push race, the command rebuilds its generated catalog state and
retries the push once. The final install refreshes links and regenerates the Codex instruction file.

Use `bin/skills-sync run --no-push` when you want to review the generated commit before you push it.
Use `bin/skills-sync run --no-update` to restore and normalize without updating upstream skills.

Run `bin/skills-sync schedule` to print a daily macOS `launchd` definition and a Linux `cron` line.
The command derives the minute from the hostname and includes the resolved `npx` directory in
`PATH`. It also records the resolved skill directory and lock file.

The skill state paths use this precedence:

1. Use `SHARED_SKILLS` for the skill directory when it is set.
2. Otherwise, use `$HOME/.agents/skills`.
3. Use `SKILLS_LOCK_FILE` for the lock file when it is set.
4. Otherwise, use `$XDG_STATE_HOME/skills/.skill-lock.json` when `XDG_STATE_HOME` is set.
5. Otherwise, use `$HOME/.agents/.skill-lock.json`.

The installer exports both resolved paths to update commands. Generated schedules record the same
paths. The old `$HOME/skills-lock.json` fallback is not part of this contract.

The installer manages `~/.claude/CLAUDE.md` and `~/AGENTS.md` with a source marker and checksum.
An unchanged reinstall does not rewrite these files. The installer backs up an existing file before
it replaces that file. If an existing file differs and provenance is unknown, the named
`instructions` step prints a diff and returns a nonzero status. A full install continues with later
steps and returns a nonzero status after they finish. Examine the backup before you run
`./install.sh --force`.
The installer keeps the five most recent backups for each managed file.

Run the Claude Code, Codex, and OpenCode verification checks after an update. Repeat the Hermes
canary if you use the experimental setup.

## Uninstall the setup

The repository has no uninstall script. Remove links one at a time so you do not delete a file that
you own.

First, list links created under the harness and shared directories:

```bash
find "$HOME/.claude" "$HOME/.codex" "$HOME/.agents/skills" "$HOME/.local/bin" \
  -type l -print
```

Examine each target with `readlink`:

```bash
readlink <link-path>
```

Use `unlink <link-path>` for links that point into `~/impstack`, the private layer, or the pinned
pstack checkout. Keep regular files and unrelated links.

Examine `~/.claude/CLAUDE.md` and `~/AGENTS.md`. Remove them if they contain the generated imports or
header from `install.sh`. The installer does not edit `~/.claude/settings.json` or
`~/.codex/config.toml`, so remove their merged entries by hand.

Examine `${XDG_CONFIG_HOME:-$HOME/.config}/opencode`. Remove the `~/AGENTS.md` instruction and the
impstack MCP entries from `opencode.json`. Remove `agents/reviewer.md`. Remove the `skills` link only
when it points to the configured shared skills directory.

Delete the repository and pstack checkout after no remaining link points into them.
