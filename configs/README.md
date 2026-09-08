# Configs

A config assigns a harness, model, and effort level to each role for one stretch of work. Choose the
config before work starts. Record any fallback in the pull request.

## Roles

| Role | Responsibility | Preferred property |
|---|---|---|
| `orchestrator` | Holds the plan and makes decisions. | Judgment. |
| `implementer` | Builds from an explicit brief in a fresh Herdr pane. Reads `service_tier` for Codex. | Throughput. |
| `reviewer` | Attacks the finished diff without the author's context. | Independence. |

The reviewer must not use the model that wrote the code. Use a different vendor when possible. If
only one vendor is available, use different model weights and require executed evidence.

## Choose a config

| Config | Harness | Orchestrator | Implementer | Reviewer | Use it when |
|---|---|---|---|---|---|
| `default` | Claude Code | Claude Opus 5 | GPT-5.6 Sol in Herdr | Fresh Claude Sonnet 5 subagent | Claude Code is available. |
| `claude-lanes` | Claude Code | Claude Opus 5 | Claude Opus 5 in Herdr | Fresh Claude Sonnet 5 subagent | Claude credits allow Opus lanes. |
| `single-vendor` | Codex | GPT-5.6 Sol | GPT-5.6 Luna | GPT-5.6 Terra | Claude is unavailable. |

The default path keeps implementation visible in Herdr panes. It gives each implementation task a
fresh Codex context. Dispatch the reviewer as a fresh Sonnet subagent. Never use Opus for a Claude
subagent.

Use `claude-lanes` when the operator allows Opus implementation panes. Require each lane to push and
open a draft pull request. Keep reviewers out of the shared checkout.

Use `single-vendor` only as the no-Claude fallback. Its reviewer uses different Codex weights from
the author and receives no shared context.

## Price reference

The following prices are US dollars per million tokens. The values come from the Anthropic pricing
page, checked 2026-09-03.

| Model | Input | Output |
|---|---:|---:|
| Claude Fable 5 | $10 | $50 |
| Claude Opus 5 | $5 | $25 |
| Claude Sonnet 5 | $2 | $10 |
| Claude Haiku 4.5 | $1 | $5 |

Check the [Anthropic pricing page](https://platform.claude.com/docs/en/about-claude/pricing) before
using these figures in a cost decision. Effort level names differ between harnesses and models.
