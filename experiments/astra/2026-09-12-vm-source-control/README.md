# Astra: VM source-control pilot

The baseline provided the better starting point for this task.
It finished sooner and used fewer tokens; the corrected subjective quality scores tied.
The judge narrowly preferred its additional recovery coverage.
This result does not establish that Impstack is generally ineffective.

This report records a private pilot. Infrastructure identities, source patches, credentials, and transcripts are withheld.
The public [metrics](metrics.json) retain aggregate evidence and model usage without session identifiers.
Numeric results below are sourced from those recorded artifacts, not new execution of the candidates.

## Question and task

Does the installed Impstack configuration improve delivery over the same lead model using its own method?

The task was to complete source control for an existing VM infrastructure repository.
Agents received a frozen, sanitized host snapshot and the same source tree.
They had to capture missing container definitions and document deployment and recovery.
They could not change production, publish remotely, or create external issues.
A local work record replaced the external tracker during the pilot.

The application was already tracked. Missing definitions belonged to the Coolify platform and its proxy.
Sentinel was managed by Coolify. A native assistant remained outside Docker.
An inactive legacy Compose definition was excluded from deployment.
Both candidates identified these ownership boundaries correctly. [sourced: private corrected review]

## Controls and treatment

Both leads used `gpt-6-astra` with high reasoning in isolated Codex CLI homes.
Both retained built-in harness instructions, system skills, and common operational safety constraints.
The CLI version was `0.153.4`. [sourced: private protocol and version check]
The prompt, starting tree, host evidence, sandbox, and tool availability matched.

Each attempt had a selected wall limit of 20 minutes, including delegated work.
Each could use up to 3 simultaneous threads at delegation depth 1. [sourced: selected protocol limits; metrics.json]
These limits were choices, not performance measurements. No token cap was imposed.

The treatment received the actual installed Impstack global instructions and skill catalog.
The baseline received neither. It chose its own method within the common constraints.

The treatment used `gpt-5.6-luna` for implementation and `gpt-5.6-terra` for review.
The baseline lead worked directly. [sourced: metrics.json model records]
Thus the comparison covers the observed instruction-and-workflow package, including its chosen delegation.
It does not isolate instruction wording from model mix or delegation overhead.

## Results

| Recorded measure | Impstack | Baseline |
|---|---:|---:|
| Elapsed seconds | 894.446 | 726.388 |
| Agent sessions | 3 | 1 |
| Input tokens, including cached input | 4,652,973 | 985,238 |
| Cached input tokens | 4,305,024 | 913,920 |
| Uncached input tokens | 347,949 | 71,318 |
| Output tokens, including reasoning | 46,403 | 20,493 |
| Total input plus output tokens | 4,699,376 | 1,005,731 |

[sourced: metrics.json, attempts]

The treatment took approximately 23% longer and consumed 4.67 times the aggregate tokens. [sourced: ratios of metrics.json attempt values]
Cached input is part of input. Reasoning output is part of output; neither is added again.
Token totals include repeated prompt processing. They do not represent unique context size or dollar cost.
Different model prices and cache rates prevent a billing conclusion from these totals alone.

### Corrected subjective review

A fresh external judge reviewed anonymous copies together, without timing or consumption data.
Its rubric used a selected scale from 0 to 4 per criterion. [sourced: protocol; metrics.json]
The anchors were absent or unsafe, major gaps, partly usable, strong with bounded gaps, and complete with direct evidence.

| Criterion | Impstack | Baseline |
|---|---:|---:|
| Scope | 4 | 4 |
| Reproducibility | 3 | 3 |
| Safety and recovery | 3 | 3 |
| Executable correctness | 3 | 3 |
| Maintainability and completion | 4 | 4 |
| Total | 17/20 | 17/20 |

[sourced: corrected private review; metrics.json; subjective judgments]

The baseline added encrypted proxy and certificate state to the existing versioned recovery archive.
It retained verification compatibility with older archives.
This additional coverage supported the judge's narrow preference.
However, its live filesystem capture still needed consistency and restoration proof.

Impstack made the required application key explicit and described managed-runtime ownership more conservatively.
Its Sentinel contract avoided inventing another deployable stack from incomplete evidence.
It documented the missing proxy backup instead of implementing it.

Both changed the normal test entry point to omit the previously included privileged container test.
Both documented a separate container-test command. This weakened the existing default verification path.
Neither demonstrated a fresh VM rebuild or a complete application restore.

## Executed checks and negative probes

The controller reran each final unit suite and offline configuration check in its original Git working tree.
Each suite reported `Ran 33 tests` and `OK`; both configuration checks passed. [sourced: private verification record]
Application dependencies were absent in the isolated environment.
Container builds, application runtime tests, deployment, and full recovery were not counted as passed.

The controller also changed disposable copies and rendered models:

| Deliberate change | Impstack validator | Baseline validator |
|---|---|---|
| Remove the application's configured user | Incorrectly accepted | Rejected |
| Change the application to host networking | Rejected | Incorrectly accepted |
| Rename the platform container | Incorrectly accepted | Rejected |
| Omit the application encryption key | Rejected | Incorrectly accepted |
| Remove the Redis command and health check | Incorrectly accepted | Incorrectly accepted |

[sourced: private mutation and extra-probe records]

These were validator gaps. The original definitions did not contain those deliberate changes.
The shared passing suites therefore did not establish adequate regression detection.
The proxy snapshot concern came from source review; no corrupt production backup was demonstrated.

## Actual workflow activation

Recorded tool calls show reads of `unslop` and `code-review` in the treatment.
They show no explicit read of `poteto-mode` or `tailnet-app`.
The treatment emitted a skill-description truncation notice. [sourced: private skill-read and initial-event records]

This measures the installed configuration's actual behavior, not complete enforcement of every available playbook.
The internal reviewer found a working-directory issue that the treatment corrected.
That useful correction did not produce a higher final rubric score on this task.
The pilot cannot identify which instructions caused the extra consumption.

## Review corrections

The first external review exposed a model name through a candidate's process ledger.
The controller discarded that review before a verdict and started a fresh judge.
Both review copies then used the common original ledger. Original candidate outputs remained intact.
Blinding remained partial because deliverable style can reveal workflow choices.

The review copies also lacked Git metadata.
That packaging choice made a candidate's Git-dependent check fail.
The controller restored neutral Git metadata to both copies and requested a narrow correction.
The check passed, and the judge withdrew the packaging finding.
The first completed rubric gave the baseline 17/20 and treatment 15/20.
The corrected result was 17/20 for both, retaining a narrow baseline preference. [sourced: private review correction records]

Implementation clocks exclude setup and external judging.
Completed judging and correction took approximately 323 seconds; the discarded review took approximately 84 seconds. [sourced: private judge status records]
Auxiliary usage is separate in [metrics.json](metrics.json).
The resumed judge reset its counters, so the initial and resumed usage were summed.
Candidate counters showed no resets. [sourced: private usage audit]
Controller conversation and inventory-helper usage were not fully measured.
Do not present candidate totals as the entire experiment's cost.

## Interpretation and next experiment

Use the baseline as the follow-up starting point for this particular task.
Retain the treatment's required-key check and explicit managed-runtime boundary.
Repair the negative-probe gaps and preserve the complete test entry point.
Verify proxy capture and restoration on disposable state before relying on the added backup.
A separate isolated VM rehearsal must establish recovery readiness.

The common prompt already supplied safety constraints and curated evidence.
This limits conclusions about Impstack's value in discovering those constraints on an unrestricted host.
Shared-machine contention, model randomness, and cache behavior were not controlled through repeated runs.
No production promotion occurred during the comparison. [sourced: private before-and-after record]

Repeat the comparison across tasks with independent implementation work before changing the default workflow.
Fix the acceptance criteria and scoring before each run.
Record actual skill activation and every descendant's consumption.
Keep required safety constraints constant and compare the workflow overhead against verified delivery gains.
Do not treat this pilot as a causal estimate, a reliability estimate, or a general model ranking.

## Publication verification

This report and its metric export are tracked by issue #51.
Publication checks cover arithmetic, local links, privacy exclusions, the repository suite, and whitespace.
The private source artifacts support provenance but are not publicly reproducible evidence.
No runtime configuration or installed instruction changes are part of this publication.
