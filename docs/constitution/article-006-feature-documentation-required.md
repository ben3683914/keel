> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 006: Feature Documentation Required

**Category:** documentation

## Status

Ratified (2026-06-05)

## Context

Every system, feature, or module that has distinct behavior deserves its own documentation. Without feature docs, knowledge lives only in code and the heads of developers — both are fragile sources of truth.

## Rule

Any new system, API, or significant behavior change requires a technical design document in docs/features/. A design document that satisfies this article also satisfies Article 002's design-before-implementation requirement. The document must follow the standard feature doc structure: metadata header, overview, interface/API reference, data flow (Mermaid diagram), dependencies, configuration, error handling, security considerations, and testing notes. If the initial doc is architecture-level only (missing full spec sections), those sections must be marked [Pending] and a task auto-created to complete them.

## Consequences

Features without documentation cannot be properly reviewed, tested, or maintained by other developers or AI agents. Institutional knowledge is lost when the original developer moves on.

## Enforcement

This is the single canonical feature-doc check. During doc review, verify that every new system, API, or significant behavior change in the diff has a corresponding feature doc in docs/features/ with the required structure. Missing docs are flagged as unresolved. Docs with [Pending] sections trigger auto-task creation for completion. Article 002 defers its structural check here.
