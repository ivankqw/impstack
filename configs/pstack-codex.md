# pstack model configuration

These routing values are fallback choices for pstack tasks without a selected factory profile.
For a selected factory plan, use its role profile subject to active instructions and available capabilities.
Report a conflict or unavailable model; do not silently substitute these defaults.

These values override the Claude model defaults in pstack skills. Codex loads this sheet through the
generated global `AGENTS.md`. The panel models use confirmed Codex slugs from this setup.

Use the cheapest model that fits the task. Use Luna Medium or High for commits, renames, spacing,
and small user-interface changes. Start a scoped feature or bug fix with Luna XHigh. Use Terra Medium
when the task is unclear and needs exploration across several parts of a repository. Use Sol Medium
for complex bugs, architecture, authentication, payments, or migrations. Escalate from Luna to
Terra, then Sol, only after the previous model struggles. Use Sol High or Max only when Terra or Sol
Medium fails. Use Sol Ultra only when the operator explicitly selects it.

feature, refactoring: gpt-5.6-luna
bug-fix: gpt-5.6-luna
perf-issue: gpt-5.6-sol
hillclimb: gpt-5.6-terra
judgment and prose: gpt-5.6-luna
strongest judgment: gpt-5.6-sol
how explorer: gpt-5.6-terra
how explainer: gpt-5.6-luna
how critics: gpt-5.6-luna, gpt-5.6-terra, gpt-5.6-sol
why investigators: gpt-5.6-terra
why synthesizer: gpt-5.6-terra
reflect tooling: gpt-5.6-luna
reflect judgment, divergent, synthesizer: gpt-5.6-terra
arena runners: gpt-5.6-luna, gpt-5.6-terra, gpt-5.6-sol
arena cross-judge pool: gpt-5.6-luna, gpt-5.6-terra, gpt-5.6-sol
swarm workers: gpt-5.6-luna
architect runners: gpt-5.6-luna, gpt-5.6-terra, gpt-5.6-sol
interrogate reviewers: gpt-5.6-luna, gpt-5.6-terra, gpt-5.6-sol
