> **Version:** 1.0.0
> **Last Updated:** 2026-08-04
> **Status:** Approved

# Conventions

Coding standards and naming conventions for this project.

## Naming

| Element | Convention | Example |
|---------|-----------|---------|
| Files | kebab-case | `user-service.ts` |
| Directories | kebab-case | `data-access/` |
| (add language-specific conventions) | | |

## File Organization

- Source code goes in `src/` (or language-appropriate directory)
- Tests mirror the source structure
- One module per file unless tightly coupled

## Code Style

- Follow the formatter configuration (Prettier, Ruff, rustfmt, etc.)
- Prefer explicit over implicit
- Keep functions short and focused
- Write self-documenting code; add comments only for "why", not "what"

## Documentation Standards

### Feature Doc Structure

All feature docs in `docs/features/` must follow this structure:

```
> **Version:** X.Y.Z
> **Last Updated:** YYYY-MM-DD
> **Status:** Draft | Approved | Deprecated

# Feature Name

## Overview
(Purpose and how it fits in the system)

## Interface / API Reference
(Tables: Name, Type, Required, Default, Description)

## Data Flow
(Mermaid diagram + prose explanation)

## State Diagram
(Mermaid stateDiagram-v2, if stateful)

## Dependencies
(What this feature depends on)

## Configuration
(Table: Option, Type, Default, Description)

## Error Handling
(Error codes table + recovery strategies)

## Security Considerations
(Auth, input validation, data protection)

## Testing Notes
(Key scenarios, edge cases, test strategy)

## Related Docs
(Links to architecture, other features)

## Open Items
(Sections marked [Pending] for future completion)
```

### Diagram Standards

- All diagrams use Mermaid code blocks (see Constitution Article 007)
- `graph` for architecture and component relationships
- `sequenceDiagram` for request/response flows
- `stateDiagram-v2` for state machines
- `flowchart` for process flows and decision trees
- Every diagram must be followed by a prose explanation

### Hub + Sub-Document Pattern

- Docs exceeding ~200 lines should be split (see Constitution Article 005)
- Hub page: summary + sub-documents table + links
- Sub-documents: reference parent hub, cover one focused topic

### Metadata

- All docs require version, last-updated, and status header (see Constitution Article 004)
- Version: major.minor.patch (restructure, new sections, corrections)

## Design Philosophy

- **Design before building** — Documentation and architecture decisions come before code
- **Self-enforcing workflows** — Hooks and gates prevent skipping steps, not willpower
- **Docs as code** — Documentation lives alongside source code and is versioned together
- **Graceful degradation** — If Python, VSCode, or GitHub CLI aren't available, setup continues with warnings
- **Isolation** — Each project is self-contained with its own VSCode, extensions, and configuration
- **Convention over configuration** — Sensible defaults that work out of the box, overridable when needed
