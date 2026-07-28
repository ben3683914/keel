> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 002: Design Before Implementation

**Category:** design

## Status

Ratified (2026-06-05)

## Context

The development process prioritizes understanding and planning over speed. Rushing to code without a design leads to rework, inconsistent architecture, and documentation gaps.

## Rule

All new features and systems must have a design document created and reviewed before implementation begins. The design doc defines the purpose, interfaces, data flow, and integration points, and follows the feature-doc structure defined in Article 006. Genuinely undecided sections may be marked [Pending] and resolved before the work is validated. Quick fixes and hotfixes are exempt, but any work that introduces a new system, API, or significant behavior change requires design-first documentation.

## Consequences

Code written without a design doc may require rework when architectural issues surface. The docs-reviewer agent will flag missing design documentation as an unresolved issue during review.

## Enforcement

The design-before-implementation principle is satisfied when a new system, API, or significant behavior change ships with a committed design document. Reviewers treat a qualifying change that arrives with no design document at all as a violation of this article. The canonical check that the document exists in docs/features/ with the required structure lives in Article 006 — defer structural and completeness findings there rather than duplicating them here.
