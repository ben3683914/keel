> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 008: Documentation Size Limit

**Category:** documentation

## Status

Ratified (2026-04-12)

## Context

Large files strain context windows, slow down selective loading, and tend to accumulate stale sections. A hard limit forces decomposition into focused, maintainable units.

## Rule

Individual documentation files must not exceed 500 lines. When a file approaches or exceeds this limit, it must be refactored using the hub and sub-document pattern (Article 005). The 500-line limit is enforced by check_doc_health and flagged as a warning during health checks.

## Consequences

Oversized docs waste context tokens, slow down get_relevant_docs responses, and increase the chance of stale content going unnoticed.

## Enforcement

check_doc_health flags any doc exceeding 500 lines. Code reviewer and doc reviewer escalate to critical if a doc exceeds 1000 lines.
