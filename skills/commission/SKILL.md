---
name: commission
description: Commission this machine for impstack setup, troubleshooting, or provisioning by probing it against the fixed contract and recording proven local state.
---

# Commission this machine

Probe the current machine. Write one global machine skill from observed results. Keep all secret values out of commands, output, and files.

## Run the probe

1. Locate the impstack repository. Use `~/impstack` unless `IMPSTACK_DIR` names another path.
2. Run `bin/commission check --repo "$IMPSTACK_DIR" --home "$HOME" --format text`.
3. Resolve the shared skill directory with `bin/skills-sync resolve-shared`.
4. Set the record path to `<shared-skills>/machine-<hostname>/SKILL.md`.
5. Set the wizard path to `$HOME/.config/impstack/commission-wizard.sh`.
6. Run `bin/commission probe --repo "$IMPSTACK_DIR" --home "$HOME" --record <record-path> --wizard <wizard-path>`.

The probe runs the fixed assertion registry in `commission.contract.json`. It records every status and exact command. The `proof.install-list` assertion is the required real proof lane.

## Handle the result

- If every applicable assertion passes, report the record path and the proof command.
- If an assertion fails, report its ID and its recorded remediation.
- If the wizard has stages, tell the operator to run its path. The wizard alone handles login, browser, URL, token, and credential input.
- If a proof cannot run, keep the failed or not-applicable result in the record. Do not describe it as verified.

Never ask the operator to paste a secret into the conversation. Never include an environment value in a report. Run an install step only when the recorded remediation names that step.
