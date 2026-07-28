> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 001: Architecture Doc as Source of Truth

**Category:** design

## Status

Ratified (2026-04-12)

## Context

The architecture document is the canonical map of the entire system. It defines how components relate, what technologies are used, and how data flows. Without a maintained architecture doc, developers make local decisions that conflict with the global design.

## Rule

The architecture document (docs/core/architecture.md) is the authoritative reference for system structure, components, and their relationships. It must be updated whenever a new system is added, a component is restructured, or the tech stack changes. All feature docs must be reachable from the architecture doc sub-documents table. The architecture doc is loaded at every session start.

## Consequences

An outdated architecture doc leads to contradictory designs, duplicated systems, and integration failures. It is the first doc any new developer or AI agent reads.

## Enforcement

Doc reviewer verifies the architecture doc is updated when new systems are introduced. get_startup_docs includes it for every session. Health checks flag if the architecture doc last-updated date is older than recent feature docs.
