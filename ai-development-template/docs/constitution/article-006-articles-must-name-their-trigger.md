> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 006: Articles Must Name Their Trigger

**Category:** general

## Status

Ratified (2026-07-28)

## Context

Adopted from the oval game's Article 030, whose context section records the decisive lesson: articles 015/018 "named the violations the whole time... yet nothing triggered enforcement until the user personally ordered an audit. The failure mode was a missing trigger, not missing law." The legacy template's constitution suffered exactly this — rules as prose hoping to be followed, checked only at commit/stop time or never.

## Rule

No constitution article may be ratified without a concrete, checkable enforcement trigger named in its Enforcement section: a specific review checkpoint, a health-check rule, a smoke test, a CI check, or an audit cadence tied to a definable event. "During review, watch for X" is acceptable only when it names which review and what observable condition constitutes a violation. Restating a principle is never a substitute for wiring its trigger; when a trigger cannot yet be automated, the article must say how and when it is manually checked and by whom.

## Consequences

The constitution decays into aspirational prose; violations accumulate silently until a crisis audit, as happened in the oval game across 130+ tasks; ratification stops meaning anything because ratified and ignored are indistinguishable.

## Enforcement

At proposal time: before calling propose_article, verify the Enforcement section names its trigger and observable condition; refuse to propose without one. At ratification: re-verify and flag trigger-less articles to the user. Periodically (constitution health check): audit existing articles for triggers that reference removed mechanisms.
