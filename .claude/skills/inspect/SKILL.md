---
name: inspect
description: Report internal system state for user review -- routing tables, constitution, health metadata, session tracking
disable-model-invocation: true
argument-hint: "[area]"
---

Report detailed system internals for user review. If an area is specified via $ARGUMENTS, focus on that area. Otherwise report all.

Areas: `doc-routing`, `code-routing`, `constitution`, `tasks`, `health`, `session`, `review-order`, `activity`, `all`

**Per-project scope.** Routing, constitution, health, and tasks are now per-project.
They report the **active project** by default; state which one. Pass `project=<slug>`
to a tool to target another project, or show the cross-project view (`project='all'`
for tasks, the rollup for status/health) for a full-workspace picture. The
constitution is two-tier — workspace articles apply to every project, plus each
project's own articles — so surface both tiers when reporting it.

## Query Strategy

**Use MCP tools first:**
- **constitution**: `list_articles` (docs-manager)
- **tasks**: `list_tasks` with board=todo, then board=working, board=testing, board=done, board=freezer (task-manager)
- **health**: `check_doc_health` (docs-manager) + `check_code_health` (code-manager)
- **doc-routing**: `refresh_doc_routing` then query via script (no MCP read tool exists)
- **code-routing**: `refresh_code_routing` then query via script (no MCP read tool exists)

**Use inspect script for areas without MCP tools:**
```
.claude/venv/bin/python .claude/scripts/shared/inspect_db.py <area>
```
Available areas: `doc-routing`, `code-routing`, `session`, `review-order`, `activity`, `all`

## Output

For each area:
1. Format as clear, readable tables
2. Flag anything unusual (stale routing, orphaned entries, missing data)
3. Show record counts
