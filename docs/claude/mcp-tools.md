# MCP Tools Reference

All mutable state stored in `.claude/claude.db` (SQLite).

MCP servers run via `.claude/venv/bin/python` (project venv created during setup, gitignored).
The venv is not project state — each developer creates their own during setup.

**Constitution injection:** `get_relevant_docs` and `get_startup_docs` append a compact constitution
summary (article number, category, title, full rule text) to every response. Doc tools inject
documentation/design/collaboration articles; startup injects all categories. Injection is two-tier:
the workspace articles plus the active project's own articles (effective set = union), so constitution
tools (`propose_article`, `ratify_article`, `amend_article`, `revoke_article`, `list_articles`) and the
compact injection operate on workspace + active project together.

## Project Scoping

Operations are scoped per project. The active project is resolved per call in this order:

1. Explicit `project=<slug>` argument — wins if present.
2. The workspace-global active-project pointer (durable; **not** session-scoped — MCP servers cannot
   read session state).
3. Inference from the files in play (then the pointer is set).
4. The `workspace` pseudo-project, for genuinely cross-cutting operations.

Every project-scoped response echoes the resolved project as a `[project: <slug>]` prefix, so a wrong
board is visible at the point of action. Routing results (`get_relevant_docs` / `get_relevant_modules`)
are **scoped to the active project**, not merely ranked by locality.

**The optional `project` argument** is available on **context tools** — those with no `task_id` to
resolve from: `create_task`, `list_tasks`, `get_project_status`, `update_project_status`,
`report_security_findings`, `log_activity`, `get_relevant_docs`, `get_relevant_modules`,
`check_code_health`, `check_doc_health`, `find_untested_files`, `run_tests`, the
review-acknowledgment tools, and the constitution tools. Passing `project='all'` gives an
across-projects rollup (e.g. `get_project_status`, `list_tasks`).

**Task-addressed tools** (those that take a `task_id`: `read_task`, `start_task`, `move_to_testing`,
`validate_task`, `update_task`, `freeze_task`, `unfreeze_task`, `move_to_todo`, `trash_task`) do **not**
take a `project` argument — task IDs are globally unique across the workspace, so each resolves its
project from the task itself and echoes it. (`update_task` can *reparent* a task by setting its
`project` field, to remediate a mis-filed task.)

## task-manager

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `list_tasks` | List tasks from boards (active project; `project='all'` for a rollup) | `board`, `category`, `project` |
| `read_task` | Get full task details | `task_id` |
| `create_task` | Create new task (filed under the active project) | `title`, `description`, `priority`, `category`, `project` |
| `start_task` | Move to working board | `task_id`, `agent` |
| `move_to_testing` | Move to testing board | `task_id`, **`test_plan`**, `notes` |
| `validate_task` | Move from testing to done | `task_id`, `notes` |
| `update_task` | Update a task field (set `field=project` to reparent) | `task_id`, `field`, `value` |
| `log_activity` | Add activity log entry (active project) | `message`, `project` |
| `freeze_task` | Defer to freezer | `task_id`, `reason` |
| `unfreeze_task` | Restore from freezer | `task_id` |
| `move_to_todo` | Move from any board to todo | `task_id`, `reason` |
| `trash_task` | Soft-delete task | `task_id`, `reason` |
| `report_security_findings` | Bulk-create S- issues (filed under the active project) | `findings[]`, `source`, `project` |
| `get_onboarding_status` | Check first-run onboarding state | (none) |
| `update_onboarding` | Update onboarding field | `field`, `value` |
| `get_project_status` | Get phase, blockers, task counts for the active project (targets the `projects` row; `project='all'` for a rollup) | `project` |
| `update_project_status` | Update phase or blockers on the active project's row | `phase`, `blockers`, `project` |

## docs-manager

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_relevant_docs` | Find relevant docs (scoped to the active project) | `task_description`, `source_files`, `project` |
| `get_startup_docs` | Load docs marked for session start (inline content) | (none) |
| `set_startup_loading` | Toggle load_at_start flag (prompts user) | `path`, `enabled`, `table` |
| `check_doc_health` | Check doc sizes, markers, constitution drift (active project) | `project` |
| `refresh_doc_routing` | Update doc routing table in SQLite | (none) |
| `write_doc` | Write a doc file and refresh routing atomically | `path`, `content` |
| `delete_doc` | Delete a doc file and refresh routing atomically | `path` |
| `acknowledge_review` | Mark doc review complete (active project) | `summary`, `unresolved_issues`, `project` |
| `propose_article` | Propose a constitution article (workspace or active-project tier) | `title`, `rule_text`, `context`, `consequences`, `enforcement`, `category`, `project` |
| `ratify_article` | Ratify a proposed article | `number`, `project` |
| `amend_article` | Amend any field(s) of an article; sets status `amended` (re-affirm via `ratify_article`) | `number` (only required), `title`, `context`, `rule_text`, `consequences`, `enforcement`, `category`, `reason`, `project` |
| `revoke_article` | Revoke an article | `number`, `reason`, `project` |
| `list_articles` | List constitution articles (workspace ∪ active project) | `status_filter`, `project` |
| `check_constitution_drift` | Compare SQLite vs markdown files | (none) |

## code-manager

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_relevant_modules` | Find relevant source modules (scoped to the active project) | `source_files`, `task_description`, `project` |
| `check_code_health` | Check file sizes and staleness (active project) | `project` |
| `refresh_code_routing` | Update code routing table in SQLite | (none) |
| `delete_module` | Delete a source file and refresh routing atomically | `path` |
| `acknowledge_code_review` | Mark code review complete (active project) | `summary`, `critical_issues`, `advisory_issues`, `project` |
| `acknowledge_security_review` | Mark security review complete (active project) | `summary`, `security_issues`, `deferred`, `project` |

## test-manager

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `find_untested_files` | Find files lacking tests (active project) | `source_files`, `project` |
| `run_tests` | Run a project's test command (active project; `project='all'` runs every project) | `files`, `all`, `project` |
| `acknowledge_tests` | Mark tests complete (active project) | `summary`, `failures`, `project` |
