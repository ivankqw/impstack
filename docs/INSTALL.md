# Install impstack

Use this guide to put the portable layer on a fresh Linux or macOS machine. The bootstrap path pins
pstack, restores upstream skills, and runs the installer.

## Prepare the machine

Install these commands first:

- `git`
- `python3`
- `bash`
- `node` with `npx`

Install `bun` if you use the pstack `watch-pr` or `orch` tools. `install.sh` warns when `bun` is
absent and continues without those tools.

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
git clone git@github.com:ivankqw/impstack.git ~/impstack
~/impstack/bootstrap.sh
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

## Merge harness settings

The installer leaves harness settings under your control. Merge these templates by hand:

- `settings/settings.template.json` into `~/.claude/settings.json`
- `settings/codex.config.template.toml` into `~/.codex/config.toml`

Replace `HOME_PATH` in the Codex template with your home directory. Restart the harness after you
change its settings.

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

Run the Claude Code and Codex verification checks after an update. Repeat the Hermes canary if you
use the experimental setup.

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

Delete the repository and pstack checkout after no remaining link points into them.
