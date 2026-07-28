> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 005: Hub and Sub-Document Pattern

**Category:** documentation

## Status

Ratified (2026-06-05)

## Context

Large monolithic documents are difficult to navigate, slow to load into context, and prone to section-level staleness. Splitting into focused sub-documents allows selective loading and targeted maintenance.

## Rule

Documentation files approaching approximately 200 lines should be evaluated for splitting into a hub page and focused sub-documents; splitting becomes mandatory before a file exceeds the 500-line hard limit defined in Article 008. The hub page contains a summary, a sub-documents table with descriptions, and links to each sub-document. Sub-documents reference their parent hub, and each covers one focused topic.

## Consequences

Monolithic docs waste context tokens when only one section is relevant. They also increase the risk of stale sections going unnoticed.

## Enforcement

check_doc_health flags docs exceeding 500 lines as oversized. Docs between 200-500 lines should be evaluated for splitting during doc review.
