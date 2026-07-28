> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 007: Mermaid for All Diagrams

**Category:** documentation

## Status

Ratified (2026-04-12)

## Context

Diagrams are essential for understanding system architecture, data flows, and state machines. Using a consistent, text-based format ensures diagrams are versioned with code, render in GitHub and VSCode, and can be maintained by both humans and AI agents.

## Rule

All technical diagrams must use Mermaid code blocks embedded in markdown. Supported diagram types: graph (architecture, component relationships), sequenceDiagram (request/response flows), stateDiagram-v2 (state machines), flowchart (process flows, decision trees). Every diagram must be followed by a prose explanation — diagrams supplement text, they do not replace it.

## Consequences

Non-Mermaid diagrams (images, ASCII art, external tools) cannot be version-controlled or auto-verified. They become stale without detection.

## Enforcement

Code and doc reviewers check that new diagrams use Mermaid syntax. External image references for technical diagrams are flagged as advisory issues.
