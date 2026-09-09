# How the setup works

I use one repository to shape Claude Code, Codex, and OpenCode. These harnesses have different
instruction and extension systems. `install.sh` gives each harness the same working method.
The design keeps stable rules in a small convention file. It loads detailed procedures as skills.
`[sourced: install.sh]`

## The base model supplies general capability

I treat a harness and its selected model as one base model. The harness supplies the work loop,
tools, context controls, permissions, and memory. The model supplies language and judgment. I can
change either part without rewriting the rest of this repository.

`configs/default.yaml` describes the Claude Code arrangement. `configs/single-vendor.yaml` describes
the no-Claude fallback. The config selects models for roles, while the harness owns execution.

## Conventions set the default method

Each session receives the portable conventions from `conventions/AGENTS.md`. Claude Code reads a
symlink through an `@import`. Codex reads a generated `~/AGENTS.md` because its documented behavior
does not include Claude imports. OpenCode loads that generated file through its global `instructions`
array. `install.sh` creates these forms in its `instructions` step.
`[sourced: install.sh, scripts/opencode_config.py, https://opencode.ai/docs/rules/]`

The convention file stays below 200 lines. `MAINTAINING.md` records that ceiling and asks one
question of each line. Would removing the line cause a mistake? The ceiling protects model attention
and pushes narrow procedures into skills.

The private layer can add another convention file. `install.sh` imports or concatenates
`$PRIVATE_CONFIG/AGENTS.md` when the file exists. I can carry the portable layer across jobs without
carrying employer details.

## Skills load detailed procedures on demand

An agent sees a skill description before it sees the skill body. The description tells the agent
when to load the procedure. The body can carry worked examples, failure cases, and verification
steps for one kind of work. This progressive disclosure keeps narrow guidance out of every session.

I keep own skills under `skills/`. The current set includes `cleanup-crew` and `dogfood-local`.
`install.sh` links each own skill into `~/.agents/skills`. It links that shared directory into
Claude Code. OpenCode reads the default shared directory without another link. If `SHARED_SKILLS`
sets another directory, the installer links that directory into OpenCode's global config directory.
`[sourced: install.sh, scripts/opencode_config.py, https://opencode.ai/docs/skills/]`

I consume upstream skills from their source origin. `skills-catalog.json` records the stable source
fields. `bin/skills-sync` restores missing skills and updates installed skills. The repository does
not copy those skill folders.

[Matt Pocock's skills repository](https://github.com/mattpocock/skills) supplies recorded skills.
`skills-catalog.json` is the current list of names and source paths.

[pstack](https://github.com/michael-denyer/pstack-claude) comes from @poteto's original pstack work.
`bootstrap.sh` clones the port from the source named by `PSTACK_REPO`. It checks out the commit in
`pstack-revision.txt`. `install.sh` links pstack skills and Codex prompt files from that checkout. The
repository neither copies pstack nor adds it to `skills-catalog.json`.

`npx skills` installs ordinary upstream skill folders under `~/.agents/skills`. The installer uses
symlinks for own skills, pstack, and harness exposure. The catalog keeps stable upstream source
data. The live lockfile keeps machine state.

Herdr runs Codex implementation agents in observable terminal panes. `skills-catalog.json` records
the `herdrdev/herdr` skill source. The installer leaves this skill absent by default. Pass
`--with-herdr` to restore it and check its metadata.
`[sourced: bootstrap.sh, install.sh, bin/skills-sync, skills-catalog.json]`

## Agents isolate a responsibility

An agent definition gives one role its own prompt and model. `agents/reviewer.md` defines the Sonnet
reviewer for the default review lane. `install.sh` links agent definitions into `~/.claude/agents`.
It renders the same prompt at `~/.config/opencode/agents/reviewer.md` for OpenCode.
`[sourced: install.sh, scripts/opencode_config.py, agents/reviewer.md]`

The OpenCode reviewer uses `mode: subagent` and denies edits. The renderer removes the Claude model
and effort fields. OpenCode selects a model from its own config.
`[sourced: scripts/opencode_config.py, https://opencode.ai/docs/agents/]`

The global primary agent uses `{"*": "ask"}` when no wildcard permission exists. The merge keeps
more specific operator permissions and an existing wildcard policy.
`[sourced: scripts/opencode_config.py, https://opencode.ai/docs/permissions/]`

The reviewer must not use the model that wrote the change. `conventions/AGENTS.md` states the rule,
and `configs/README.md` explains the reason. Models can share blind spots with another run of the
same weights. A different model gives the review another failure pattern. The single-vendor config
uses a different OpenAI model when Codex holds every role.

The default config dispatches the reviewer as a fresh Claude Sonnet subagent. The reviewer receives
the repository path and diff range, but none of the author's conversation context.

## Configs make role choices explicit

A config assigns a harness, model, and effort to each role. `configs/default.yaml` and
`configs/single-vendor.yaml` hold those choices. `configs/README.md` explains when to use each
config.

Named configs turn several model choices into one operator decision. They expose compromises.
For example, `configs/single-vendor.yaml` marks its reviewer as `cross_vendor: false` and requires a
different model with no shared context.

`configs/pstack-codex.md` maps pstack roles to confirmed Codex model names. `install.sh` appends that
file to the generated Codex instructions and links it at `~/.codex/pstack-models.md`.

## Hooks fire on configured events

The model decides whether to load a skill. A hook does not depend on that decision. The harness runs
a hook when a configured event matches.

`hooks/review_reminder.py` adds advice before a shell command that contains `git push`. It asks the
operator to dispatch the Sonnet reviewer as a fresh subagent. `hooks/cleanup_crew_after_pr.py` adds
tracker advice after a pull request opens. Both hooks catch errors and exit without blocking work.

`install.sh` links each hook into `~/.claude/hooks` and `~/.codex/hooks`. It does not edit harness
settings. `settings/settings.template.json` and `settings/codex.config.template.toml` show the
registrations that an operator must merge.

## MCP declarations keep credentials outside Git

`mcp/servers.json` declares MCP server names and URLs. A server can name a header environment
variable through `header_env`. The Claude installer skips that server when the variable has no value.
`[sourced: install.sh, mcp/servers.json]`

A tenant URL identifies an account, so the executor declaration uses `url_env` with
`EXECUTOR_MCP_URL`. The installer reads the URL from the environment and skips the server when the
variable has no value. The file stores no API key or tenant URL.

The MCP step calls the Claude and Codex CLIs when they are present. Codex accepts bearer-token
environment variables. It cannot reproduce arbitrary HTTP header names, so the installer prints a
skip reason for those entries.
`[sourced: install.sh]`

The same step merges remote entries into OpenCode's global JSON config. Header and URL values use
OpenCode environment references. The installer omits an environment-based URL when its variable is
not set. The merge keeps unrelated user config and does not rewrite unchanged content.
`[sourced: install.sh, scripts/opencode_config.py, mcp/servers.json]`

Hermes support remains experimental. `docs/INSTALL.md` describes the manual context, skill, MCP, and
canary steps. The installer does not edit `~/.hermes/config.yaml`.

## The layers keep different change rates apart

I can change a model through a config, refine a procedure in one skill, or add an event reminder in
a hook. Each change has one home. The harness can improve while the portable layer keeps my method,
and an upstream skill can improve without losing its source history.

## Terms

| Term | Meaning |
|---|---|
| Base model | The harness and selected model treated as one starting system. |
| Harness | The program that runs the model, supplies tools, manages context, and controls the work loop. |
| Convention | A rule that every session receives through an instruction file. |
| Skill | A Markdown procedure that an agent loads for a matching task. |
| Fat skill | A skill with enough examples, constraints, and failure cases to guide judgment. |
| Own skill | A skill maintained in this repository under `skills/`. |
| Upstream skill | A skill maintained elsewhere and recorded in `skills-catalog.json` or `pstack-revision.txt`. |
| Config | A named set of model and effort choices for each role. |
| Role | One responsibility in a stretch of agent work. |
| Orchestrator | The role that holds the plan and makes decisions. |
| Implementer | The role that builds from an explicit brief. |
| Reviewer | The role that attacks a finished change. |
| Lane | One independent stream of work or review. |
| Hook | A program that a harness runs for a configured event. |
| Lockfile | JSON state from the `skills` CLI, including source and machine data. |
| Portable layer | Methods and tools that can move between jobs and machines. |
| Private layer | Employer, host, person, and domain details kept outside this repository. |
