> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 001: Engine/Data Separation

**Category:** design

## Status

Ratified (2026-07-28)

## Context

Adopted from the oval game's Article 015 (engine/content separation), generalized during the T-001 rewrite goal-setting. The rewrite's flexibility goals (per-feature toggles G4, model overlays G7, harness adapters G6, user extensions G10) all depend on behavior being data the system loads rather than code the system is. The legacy template's hardcoded TypeScript review conventions, magic-number scoring weights, and prose-embedded enforcement are the failure mode this prevents.

## Rule

Framework engine code contains no workspace-specific, harness-specific, or model-specific logic or literals. All per-workspace behavior — feature toggles, conventions, thresholds, model directive overlays, harness capability declarations, review rubric parameters, scoring weights — arrives as declared, schema-validated data loaded at runtime. Adding support for a new harness, model, or convention must be a data change, never an engine code change per instance.

## Consequences

Every new harness, model, or user convention becomes an engine fork; toggles and overlays stop composing; the public framework cannot be extended without patching core code, defeating the rewrite's central purpose.

## Enforcement

During design review: reject designs that place per-instance behavior in engine code. During code review: flag harness names, model names, workspace-specific values, or tunable constants appearing as literals in engine modules instead of declared data. When the engine gains CI: add a literal-scan check.
