---
name: project-status
description: Quick project status summary for the active project, with a cross-project rollup
disable-model-invocation: true
---

Status is per-project. Report the **active project** by default, and state which
project that is.

1. Call `get_project_status` (task-manager MCP) for phase and blockers. It reports
   the active project's phase/blockers/counts and appends a per-project rollup
   across all projects.
2. Call `list_tasks` for each board (todo, working, testing, done) to get counts
3. Show recent activity via `.claude/venv/bin/python .claude/scripts/shared/inspect_db.py activity`
4. Flag any blockers or stale items

Pass `project=<slug>` to target another project. Keep the output concise -- 10
lines max.
