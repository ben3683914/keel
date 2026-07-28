> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 009: Tables Over Prose for Structured Data

**Category:** documentation

## Status

Ratified (2026-04-12)

## Context

API parameters, configuration options, field definitions, error codes, and other structured data are easier to scan, compare, and maintain in table format. Prose descriptions of structured data become ambiguous and hard to update.

## Rule

All structured data in documentation must use markdown tables with consistent columns. Field definitions: Name, Type, Required, Default, Description. API parameters: Parameter, Type, Description. Error codes: Code, Meaning, Resolution. Configuration: Option, Type, Default, Description. Tables must be followed by prose only when additional context is needed for complex fields.

## Consequences

Prose-based field descriptions are harder to maintain, easier to miss updates, and more ambiguous for implementers.

## Enforcement

Doc reviewer checks that structured data uses table format. Prose lists describing fields, parameters, or options are flagged as advisory issues.
