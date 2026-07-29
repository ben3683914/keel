> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 005: Every State Kind Is Inspectable

**Category:** design

## Status

Ratified (2026-07-28)

## Context

Adopted from the oval game's Article 022 (admin observability for persisted data), generalized during T-001. Legacy's /inspect skill was an afterthought bolted on for areas with no read tool; coverage rotted as state was added. Debugging a framework that manages its own state requires that no state be opaque.

## Rule

Every change that adds or alters persisted state — a new entity type, a new derived index, a new ephemera file, a new config surface — must include a corresponding inspection surface in the same change: a read tool, a skill section, or a projection through which the state is viewable without reading raw storage internals. Generic inspection (serialize any entity by path) is the required floor; first-class display is encouraged where it aids debugging. Inspection reads must never mutate state.

## Consequences

Debugging visibility degrades silently as the framework grows; users and maintainers resort to spelunking raw files, defeating the state API; support for a public framework (G-audience) becomes guesswork.

## Enforcement

During design review and code review: any change touching persisted state must show its inspection path; flag additions without one. The health-check registry should include a coverage check once the inspection surface is registry-driven.
