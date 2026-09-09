---
name: factory-workflow
description: >-
  Use when executing an Impstack factory configuration across native Codex app
  tools or terminal agents through Herdr. Resolve selected profiles and preserve
  task handoffs through implementation and independent review.
---

# Execute a factory plan

Resolve this skill's real path before locating the repository root.
Read `docs/FACTORY.md` from that root for the CLI and record contracts.
Use the operator's selected factory config. Do not replace it with a legacy YAML preset.

## Prepare the handoff

- Read the task, acceptance criteria, active instructions, and selected config.
- Run `bin/factory --help`, then validate the config and generate its plan using the documented commands.
- Keep the plan and task records outside the checkout's tracked files.
- Resolve every selected profile against the current session's actual capabilities.
- Report instruction conflicts or unsupported model settings before dispatch.
- Record any authorized fallback in the plan and work record.

A successful validation checks declared data. It does not prove that a model or tool is available.
Module declarations do not install tools or grant access.

## Dispatch through the selected execution method

For native execution, use the app tools available in this session.
Discover their definitions before calling them. Honor their context, model-selection, and permission limits.
Do not invent a dispatch API or translate a native app profile into a terminal command.

For Herdr execution, load the installed Herdr skill and discover the local CLI.
Use a separate worktree and agent context for each implementation lane.
Pass model settings only through options supported by that harness.
Keep approval behavior under the active permission policy.

Give the implementer the task brief and the expected result contract.
Use the selected workflow procedure for implementation. The factory plan does not replace pstack's method.

## Verify the result and review

Validate the result against its brief with the factory CLI.
Examine its artifacts and rerun checks that support acceptance.
Treat terminal idle, a report file, and structural validation as insufficient completion evidence.
Keep blocked or unresolved work explicit.

Give the selected reviewer an isolated checkout at the implementation commit and fresh context.
Require the defect and standards reviews against the same fixed point before pushing.
Record any model-independence limitation. Do not substitute a shared-context review silently.

Open a draft pull request only after the required reviews pass.
Preserve the plan, results, and evidence references in the work record for resumption.
Merge only under applicable authorization. Leave release tags to the operator.
