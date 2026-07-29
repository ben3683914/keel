> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 004: State Declares Its Kind

**Category:** design

## Status

Ratified (2026-07-28)

## Context

Established during T-001's state-model decision. The legacy template's worst failures traced to one root cause: six different kinds of state fused into one tracked binary SQLite file — session ephemera shipped in releases, history destroyed by GC, unmergeable team conflicts. The rewrite's taxonomy (truth / derived / ephemera / history) makes storage rules follow from classification.

## Rule

Every piece of persisted state must declare its kind and follow that kind's storage rules. Truth (config, governance, work items, curated routing signals) lives as per-entity, mergeable text files tracked in git. Derived state (indexes, projections, caches) is gitignored, rebuildable from truth, and never tracked. Ephemera (session tracking, active-project pointer, watermarks, gate evidence) is per-machine local and never tracked. History lives in git itself, never destructively garbage-collected. No binary state files in git, ever.

## Consequences

State kinds re-fuse: derived files cause guaranteed merge conflicts, ephemera leaks between machines and into releases, history gets deleted, and team workflows (G3) break — reproducing the legacy claude.db disaster the rewrite exists to fix.

## Enforcement

During design review: every feature that persists anything must name each item's kind and its storage location; reject unclassified state. During code review: flag writes of derived or ephemeral data into tracked paths, tracked binary formats, and destructive deletion of history. The state-integrity health kind should verify gitignore coverage of derived/ephemera paths.
