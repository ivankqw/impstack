# Factory configuration

Use the factory CLI to validate declarative profiles, recipes, assignments, task briefs, and results.
It uses Python and the standard library.
It does not install modules, authenticate a provider, dispatch a session, or change permission policy.

## Validate the example

Run these commands from the repository root:

    bin/factory validate configs/factory/reviewed-change.json --format json
    bin/factory plan configs/factory/reviewed-change.json --assignment hybrid
    bin/factory validate-brief configs/factory/brief.json --config configs/factory/reviewed-change.json
    bin/factory validate-result configs/factory/result.json --brief configs/factory/brief.json --config configs/factory/reviewed-change.json

The plan is a handoff for the caller.
It contains no runnable harness command.

## Use a plan for real work

Copy the example configuration into your private configuration directory.
Replace placeholder models in the selected assignment's profiles with models available in your harness.
Keep credentials outside the configuration.

Give your agent the configuration path, the assignment name, and the task's acceptance criteria.
Ask it to follow [factory-workflow](../skills/factory-workflow/SKILL.md) from this checkout.
That skill consumes the plan and uses the calling session's execution tools.
The existing installer also links the skill and CLI when you install the personal preset.

Save the emitted plan with the task record before dispatch.
Use the same configuration snapshot when validating the returned result.
A profile name alone does not detect a later change to that profile's model.

## Configuration

A configuration has named profiles, recipes, assignments, and optional modules.

- A profile names a harness, transport, provider, model, and harness-specific options.
- A recipe names the required roles, ordered handoff steps, and shared invariants.
- An assignment maps every recipe role to one profile.
- A module records an optional integration. It does not install or enable it.

Use native-codex-app only with the codex-app harness.
Use herdr-cli only with claude-code, codex-cli, or opencode.
A hybrid assignment includes at least one native Codex app profile and one Herdr terminal profile.

The validator rejects missing profiles, unknown roles, invalid transport pairings, and reviewer identity conflicts.
When a reviewer sets cross_vendor to true, it must use a different provider from the implementer.
harness_options and provider_options are free-form data for the selected harness.
The validator does not treat model names or option values as available capabilities.
Identity checks compare declared provider and model strings.
Provider and model identifiers cannot contain surrounding whitespace.
Resolve aliases and gateway model names before relying on review independence.

## Profile substitution

The example has native and native-alternate-implementer assignments.
They use the same reviewed-change recipe.
Only the implementer profile changes:

    bin/factory plan configs/factory/reviewed-change.json --assignment native
    bin/factory plan configs/factory/reviewed-change.json --assignment native-alternate-implementer

## Brief and result records

A brief binds a task to its recipe, assignment, transport, role-to-profile references, base commit, acceptance criteria, and required checks.
The base commit is the revision at handoff.

A result repeats that binding and records the produced actual_commit, status, artifacts, verification evidence, and unresolved work.
For a successful result, every brief check needs zero-exit evidence and unresolved_work must be empty.

Validate a brief with --config to bind it to an assignment.
Validate a result with both --brief and --config to compare every shared binding and required check.

## Execution boundary

For native Codex app work, use only the capabilities exposed in the current app session.
For Herdr work, discover the installed Herdr command and supported harness options.
Active system, user, repository, skill, and permission instructions remain authoritative.
Report a conflict before dispatch.
