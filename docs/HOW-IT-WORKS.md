# How the setup works

Impstack separates the workflow from the agents that execute it.
A recipe defines the handoffs and review requirements. A factory config assigns agent profiles to roles.
The selected harness supplies tools, permissions, context controls, and session lifecycle.

## Profiles and execution paths

A profile names a harness, execution method, provider, model, and native options.
The role assignment selects a profile without changing the recipe.
The factory CLI validates these declarations and produces a plan for the calling agent.
See [the factory contract](FACTORY.md) for commands and examples.

Native Codex app plans are handoffs to tools available in the current app session.
They do not imply a public dispatch API or guaranteed model-selection support.
Herdr plans are handoffs for terminal agents using Claude Code, Codex CLI, or OpenCode.
A hybrid configuration mixes native app and Herdr profiles.
The example uses an app coordinator and Herdr implementation lanes; other mixed role assignments are valid.

Active instructions and permission policy remain authoritative.
If the selected profile conflicts with them, report the conflict before dispatch.
A plan does not install a harness, authenticate a provider, or grant permission to merge.

## Shared contracts and optional integrations

The task brief records the requested work. The result records what happened and what remains unresolved.
Verification evidence must be checked against the acceptance criteria.
A valid result file proves its structure, not the truth of its contents.

Tracking, MCP connections, browser tools, and retrospective tools are replaceable integrations.
Module declarations record choices; the factory CLI does not provision them.
The existing bootstrap still installs the personal preset described below.

## Conventions set the default method

Each session receives the portable conventions from `conventions/AGENTS.md`. Claude Code reads a
symlink through an `@import`. Codex reads a generated `~/AGENTS.md` because its documented behavior
does not include Claude imports. `install.sh` creates both forms in its `instruction files` block.

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
Claude Code.

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

Herdr runs Codex implementation agents in observable terminal panes. `skills-catalog.json` records the
`herdrdev/herdr` skill source. `bootstrap.sh` stops if restoration does not create the Herdr skill.

## Agents isolate a responsibility

An agent definition gives one role its own prompt and model. `agents/reviewer.md` defines the Sonnet
reviewer for the default review lane. `install.sh` links agent definitions into `~/.claude/agents`.

The reviewer must not use the model that wrote the change. `conventions/AGENTS.md` states the rule,
and `configs/README.md` explains the reason. Models can share blind spots with another run of the
same weights. A different model gives the review another failure pattern. The single-vendor config
uses a different OpenAI model when Codex holds every role.

The default config dispatches the reviewer as a fresh Claude Sonnet subagent. The reviewer receives
the repository path and diff range, but none of the author's conversation context.

## Factory configs and legacy presets

[Factory configurations](FACTORY.md) are consumed by `bin/factory`.
They separate profile definitions from role assignments and a shared recipe.

The existing YAML files under `configs/` describe personal presets for an agent to read.
The installer does not parse them into a factory plan.
`configs/README.md` distinguishes those presets from executable configuration.

`configs/pstack-codex.md` supplies fallback model routing for pstack.
The installer appends that file to generated Codex instructions.
A selected factory profile takes precedence over those routing defaults, subject to active instructions.

## Hooks fire on configured events

The model decides whether to load a skill. A hook does not depend on that decision. The harness runs
a hook when a configured event matches.

`hooks/review_reminder.py` adds advice before a shell command that contains `git push`. It asks the
operator to dispatch the selected reviewer profile with fresh context. `hooks/cleanup_crew_after_pr.py` adds
tracker advice after a pull request opens. Both hooks catch errors and exit without blocking work.

`install.sh` links each hook into `~/.claude/hooks` and `~/.codex/hooks`. It does not edit harness
settings. `settings/settings.template.json` and `settings/codex.config.template.toml` show the
registrations that an operator must merge.

## MCP declarations keep credentials outside Git

`mcp/servers.json` declares MCP server names and URLs. A server can name a header environment
variable through `header_env`. The installer skips that server when the variable has no value.

A tenant URL identifies an account, so the executor declaration uses `url_env` with
`EXECUTOR_MCP_URL`. The installer reads the URL from the environment and skips the server when the
variable has no value. The file stores no API key or tenant URL.

The MCP installation block calls both the Claude and Codex CLIs when they are present. Codex accepts
bearer-token environment variables, but it cannot reproduce arbitrary HTTP header names. The
installer prints a skip reason for those entries.

Hermes support remains experimental. `docs/INSTALL.md` describes the manual context, skill, MCP, and
canary steps. The installer does not edit `~/.hermes/config.yaml`.

## The layers keep different change rates apart

I can change a model through a config, refine a procedure in one skill, or add an event reminder in
a hook. Each change has one home. The harness can improve while the portable layer keeps my method,
and an upstream skill can improve without losing its source history.

## Terms

| Term | Meaning |
|---|---|
| Profile | A named harness, execution method, provider, model, and native options. |
| Harness | The program that runs the model, supplies tools, manages context, and controls the work loop. |
| Convention | A rule that every session receives through an instruction file. |
| Skill | A Markdown procedure that an agent loads for a matching task. |
| Fat skill | A skill with enough examples, constraints, and failure cases to guide judgment. |
| Own skill | A skill maintained in this repository under `skills/`. |
| Upstream skill | A skill maintained elsewhere and recorded in `skills-catalog.json` or `pstack-revision.txt`. |
| Factory config | Profile definitions and role assignments used with a workflow recipe. |
| Recipe | Shared task handoffs and review requirements. |
| Transport | The declared execution method used by the calling agent. |
| Role | One responsibility in a stretch of agent work. |
| Orchestrator | The role that holds the plan and makes decisions. |
| Implementer | The role that builds from an explicit brief. |
| Reviewer | The role that attacks a finished change. |
| Lane | One independent stream of work or review. |
| Hook | A program that a harness runs for a configured event. |
| Lockfile | JSON state from the `skills` CLI, including source and machine data. |
| Portable layer | Methods and tools that can move between jobs and machines. |
| Private layer | Employer, host, person, and domain details kept outside this repository. |
