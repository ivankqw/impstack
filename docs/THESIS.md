# Why a composable code factory

Impstack began as a personal configuration for an imperfect operator.
Its useful unit is now a repeatable workflow across agents: a brief, isolated work, evidence, review, and a handoff.

The workflow should survive a change of model or harness.
An operator can coordinate in the Codex app and send implementation work to terminal agents through Herdr.
Another operator can keep the same workflow inside the app.
Neither choice changes what counts as verified work.

## The forcing boundary

A harness owns tools, context, permissions, and session lifecycle.
Impstack cannot promise interchangeable runtime capabilities merely because profiles share a file format.
It can make the choices explicit and validate the data passed between participants.

That boundary keeps Impstack a recipe rather than another scheduler.
A plan names the requested execution path. The caller checks available capabilities before dispatch.
An unsupported path stays unsupported; the caller does not silently choose another model or weaken review.

## Independent choices

A role names a responsibility. A profile names the harness, execution method, provider, model, and native options.
A workflow recipe names the work and its review requirements.
Optional integrations supply tracking, tools, browser access, or retrospective input.

These choices change at different rates.
Replacing an implementation model should not require rewriting the workflow or the reviewer's task.
Replacing Linear with GitHub should not remove the requirement to record acceptance criteria.

## The operator remains accountable

The "code factory" phrase is a metaphor for a repeatable production process.
It does not imply that terminal activity is progress or that an agent's success report is proof.
The operator receives a change, its evidence, and unresolved risks before authorizing the next consequential action.

[Backpass](https://github.com/kunchenguid/backpass) helped shape the original correction loop.
It remains one way to find lessons in transcripts. It does not define the product or its required runtime.
[pstack](https://github.com/michael-denyer/pstack-claude) supplies workflow procedures rather than another execution engine.
Garry Tan's [thin harness, fat skills](https://github.com/garrytan/gbrain/blob/master/docs/ethos/THIN_HARNESS_FAT_SKILLS.md) explains another influence on this boundary.

## What would make this layer unnecessary

If a native harness supplies the same portable work contracts and role choices, remove the duplicate layer.
If configuration adds more work than it saves, reduce the configuration.
If a recipe cannot explain how its evidence supports acceptance, fix the recipe before adding more agents.

The initial implementation validates configuration and task handoffs.
It does not establish deployment readiness or prove that every declared model can run on a given machine.
