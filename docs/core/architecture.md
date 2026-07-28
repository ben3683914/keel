> **Version:** 0.1.0
> **Last Updated:** 2026-06-05
> **Status:** Draft

# Architecture

## Overview

(Fill in during onboarding: what this system does and why it exists.)

## System Diagram

```mermaid
graph TD
    subgraph "(define system boundaries)"
        A["Component A"] --> B["Component B"]
    end
```

(Replace with actual system architecture after onboarding.)

## Components

| Component | Purpose | Location |
|-----------|---------|----------|
| (add components as they are built) | | |

## State Model

The template is **projects-first**. There is always a `projects` collection in `claude.db`.
Row `id=1` is the always-present `workspace` pseudo-project — the **umbrella only**: it holds
cross-cutting tasks, the workspace tier of constitution articles, and serves as the resolution
fallback. **You never work directly on the workspace row.** Every actual project — regardless of
workspace shape — is a real `projects[]` entry (`slug`, `name`, `path`, `source_roots`,
`source_extensions`, `test_command`) living in its own `./<slug>/` subfolder, created via the
shared `new_project.py` helper. Nothing a user works on ever lives at the repo root; the root
holds only the engine (`.claude/`), workspace-tier docs, and each project's subfolder.

| Shape | `projects[]` | Enforcement | Layout |
|-------|--------------|-------------|--------|
| single | 1 entry | `full` | `./<slug>/` |
| scratch | 1 entry | `minimal` | `./<slug>/` |
| multi | N entries | `full` | `./<slug-1>/`, `./<slug-2>/`, … |

"Single → multi" is simply adding more entries via `/add-project`; there is no migration and no
structural difference — single is just "one project."

**Per-project scoping.** Boards, status (phase/blockers), reviews, health, routing, and the
constitution are all scoped per project (the old singleton `project_status` table is gone —
phase/blockers live on each `projects` row). Tasks, routing, the activity log, and constitution
articles all carry a `project_id`; `review_order` and `health_metadata` are keyed per project.
Task IDs are globally unique across the workspace.

**Active project.** A workspace-global, durable pointer marks the active project (it is **not**
session-scoped — MCP servers cannot read session state). Resolution order for any project-scoped
operation: explicit `project=<slug>` argument > active pointer > inference from edited files >
`workspace` fallback. The pointer follows edited files, and every project-scoped response echoes
`[project: <slug>]`. The SessionStart hook emits `ENFORCEMENT:`, `ACTIVE_PROJECT:`, and
`PROJECTS:` lines.

**Two-tier constitution.** Workspace-tier articles apply to every project; each project may add
its own. The effective set for a project is the union (workspace ∪ project), numbered per tier.
Workspace-tier markdown lives in `docs/constitution/`; a project's own articles live in
`<project.path>/docs/constitution/`.

**Enforcement** is a workspace-level setting (`full` | `minimal`). `minimal` is the lightweight
mode (no review pipeline, minimal onboarding); `full` activates reviews, doc enforcement,
constitution, and task gates.

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| (filled during onboarding) | | |

## Data Flow

```mermaid
sequenceDiagram
    participant User
    participant System
    User->>System: (define primary interaction)
    System-->>User: (define response)
```

(Replace with actual data flow after first feature is designed.)

## Sub-Documents

| Document | Description |
|----------|-------------|
| (feature docs linked here as they are created) | |

Feature docs live in `docs/features/`. Each new system or feature gets its own doc following the standard structure defined in [conventions.md](../guides/conventions.md).

## Related

- [Constitution](../constitution/index.md) — project rules
- [Conventions](../guides/conventions.md) — coding and documentation standards
