---
name: health
description: Run a project health check -- doc health, code health, constitution drift, and stale task detection
disable-model-invocation: true
---

Health checks are per-project. They run against the **active project** by default;
state which project that is. Pass `project=<slug>` to target another, or
`project='all'` to audit every project for a full-workspace picture.

Run a comprehensive health check:
1. Call `check_doc_health` (docs-manager MCP)
2. Call `check_code_health` (code-manager MCP)
3. Call `check_constitution_drift` (docs-manager MCP) -- drift is per-project too
   (workspace-tier articles plus the project's own articles)
4. Check for stale tasks (tasks in working status for >3 days) via `list_tasks` with board=working
5. Summarize all findings concisely
