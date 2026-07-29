> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 002: Idempotent, Reproducible Operations

**Category:** design

## Status

Ratified (2026-07-28)

## Context

Adopted from the oval game's Article 014 (deterministic simulation core), generalized to framework operations during T-001. Ben's core requirement for the rewrite is a flexible, idempotent framework supportable long-term. Setup, index rebuilds, updates, reconciliation, and onboarding must all be safely re-runnable — legacy's order-dependent onboarding and unmergeable state were direct consequences of violating this.

## Rule

Every framework operation — setup, index rebuild, update application, reconciliation, onboarding steps, health checks — must be idempotent: re-running it from any intermediate or completed state converges to the same correct result. Derived state (indexes, projections, caches) must always be rebuildable from tracked truth, byte-equivalently on any machine. Operation outcomes must never depend on wall-clock time, randomness, or execution order beyond explicitly declared dependencies.

## Consequences

Half-completed operations strand users in unrecoverable states; moving machines or resuming after a crash requires manual surgery; derived state diverges silently between teammates; the one-setup-script portability goal (G5) becomes impossible.

## Enforcement

During design review: every proposed operation must state what happens when re-run and when interrupted midway; reject designs whose steps have implicit ordering. During code review: flag unseeded randomness, wall-clock dependence in outcomes, and write paths that cannot heal from partial completion. Smoke tests should include a run-twice-and-compare check for derived state.
