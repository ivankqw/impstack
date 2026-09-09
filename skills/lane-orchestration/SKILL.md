---
name: lane-orchestration
description: >-
  Use when work must move through implementation lanes in Herdr, from ticket
  briefs through independent review, draft pull requests, an authorized merge,
  and cleanup.
---

# Orchestrate lanes

Run each implementation task in its own worktree and Herdr pane. Use your worktree helper so the
worktree receives its required local configuration.

## Lane operating rules

- Review in a throwaway worktree pinned to the reviewed SHA. Leave the shared checkout untouched.
  One reviewer's unreverted probe removed a guard from an implementation lane.
- Re-verify a fix by resuming the same reviewer with the new SHA. It must rerun the probes that
  found the defect.
- Mutate one layer at a time. Remove the app check alone, then the database constraint alone. A test
  that fails only when both are absent proves neither layer.
- A lane is done only after it pushes the branch and opens the draft pull request. Require a
  one-line pull-request URL sentinel file. Lanes have written reports without pushing or opening a
  pull request.
- Monitor report and sentinel files with a persistent monitor. Shell sleep loops die with sessions.
- Run commands beyond the harness timeout detached. Write their output to a log file because the
  harness stops long foreground commands.
- Parallel schema revisions collide on revision numbers. The second lane to merge renumbers its
  revision and rebases.

## Write each brief

Create one brief file per ticket. Put these parts in the file:

1. Add the common hard-rules block.
2. Add the ticket text and acceptance criteria.
3. Name the worktree, branch, and verification commands.
4. Name the report path.
5. Name a separate pull-request URL sentinel path.

Tell the lane to write only the pull-request URL into the sentinel file. A report without a pushed
branch and a draft pull request is incomplete.

## Start a Codex pane

Find the worktree's root pane. Start Codex with a new agent name and explicit budget flags:

```bash
herdr agent start <new-name> --kind codex --pane <pane-id> -- -c model_reasoning_effort=<config.effort> -c service_tier=<config.service_tier>
```

The model default tier can enable fast service `[observed: 2026-09-08 operator]`. Herdr reuses an
old command when you restart an agent name `[observed: 2026-09-08 operator]`. Use a new name when
the command changes.

## Start a Claude pane

When the selected config permits Claude implementation lanes, run:

```bash
herdr agent start <new-name> --kind claude --pane <pane-id> -- --model <config.model> --effort <config.effort> --permission-mode acceptEdits
```

At the first Bash permission prompt, choose "switch to auto mode". Do not send stray keystrokes to
a working pane. A stray key can interrupt the agent `[observed: 2026-09-07 operator]`.

## Deliver the prompt

Send one instruction:

```text
Read <brief> and do exactly what it says.
```

Monitor the report and sentinel paths. Use a persistent monitor instead of a shell sleep loop.
Shell waiters can die with the session `[observed: 2026-09-07 operator]`. Run commands beyond the
harness timeout detached and write their output to a log file.

## Review and fix

Dispatch a fresh reviewer against the pushed SHA. Give the reviewer a throwaway worktree pinned to
that SHA. The reviewer must leave the shared checkout untouched and revert every probe.

If review finds a defect, write a fix brief for the implementation lane. Resume the same reviewer
with the new SHA after the fix. Require the reviewer to rerun its probes.

Run the standards and specification review against the same fixed point. Do not merge until both
review lanes approve.

## Merge and clean up

Merge only under a named grant that covers the repository and merge action. State what the merge
triggers before you use the grant. Verify the reviewed SHA, branch state, checks, and pinned merge
head.

After the merge, remove the worktree with your worktree helper. Stop its Herdr workspace and remove
temporary brief, report, sentinel, and log files.
