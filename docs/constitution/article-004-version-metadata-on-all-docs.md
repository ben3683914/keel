> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 004: Version Metadata on All Docs

**Category:** documentation

## Status

Ratified (2026-06-05)

## Context

Documentation without metadata is impossible to maintain at scale. Knowing when a doc was last updated, its current status, and what version it reflects enables the health check system and reviewers to detect staleness.

## Rule

Every documentation file in docs/ must include a metadata header with version (X.Y.Z), last updated date (YYYY-MM-DD), and status (Draft, Approved, or Deprecated). Version increments: major (restructure/rewrite), minor (new sections/significant changes), patch (corrections/clarifications). Status must be kept current — a doc that falls behind the code should be marked Draft until updated. Auto-generated files are exempt from the metadata-header requirement: files regenerated from SQLite, such as the constitution articles under docs/constitution/ and project/board-snapshot.md, instead carry an auto-generation marker (a 'do not edit' banner or a generation timestamp), and their provenance — and, where applicable, version and status — is tracked in the source data rather than in a manual header.

## Consequences

Docs without metadata cannot be audited for staleness. Reviewers and health checks have no baseline to compare against.

## Enforcement

Doc reviewer checks for metadata header on all reviewed docs. Missing metadata is flagged as an unresolved issue.
