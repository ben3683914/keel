> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 010: Plan Completion Verification

**Category:** workflow

## Status

Ratified (2026-04-12)

## Context

AI agents can lose track of plan items during complex implementations, especially when plans span multiple files or systems. External reviews (code, docs, security, tests) catch issues but run after implementation is complete. A self-verification step catches gaps immediately, before review overhead is incurred.

## Rule

Every implementation plan must include a final verification step where the implementing agent audits its own work against the original plan. The self-audit must check: (1) every plan item was completed, (2) no placeholder or TODO code was left behind, (3) tests cover new or modified code. If gaps are found, fix them before proceeding to the review pipeline. This step is in addition to, not a replacement for, the code/docs/security/test review sequence.

## Consequences

Without self-verification, incomplete implementations enter the review pipeline, wasting review cycles on obvious gaps. Reviewers should catch substantive issues, not missing plan items.

## Enforcement

Plan mode should include the verification step by default. Code reviewer flags if the plan had items that appear unimplemented in the diff.
