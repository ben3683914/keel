# Hooks Reference

All hooks read/write SQLite (`.claude/claude.db`), not JSON or markdown files.

**Portability:** Hook commands use `$(git rev-parse --show-toplevel)` to resolve script paths
from the git root. This ensures hooks work regardless of Bash's current working directory.
Hooks use the system `python3` on PATH. MCP servers use `.claude/venv/bin/python`
(see [mcp-tools.md](mcp-tools.md)).

## Enforcement Registration

Hooks are registered in `settings.json` based on the workspace `enforcement` level
(`full` | `minimal`). The assembly script (`assemble.py`) builds settings.json from partials
in `.claude/scaffolds/settings/`; the enforcement gates are omitted when `enforcement` is
`minimal`.

| Hook | minimal | full |
|------|:---:|:---:|
| cleanup_boards.py | Y | Y |
| guard_boards.py | Y | Y |
| track_modifications.py | Y | Y |
| commit_quality.py | Y | Y |
| constitution_watch.py | Y | Y |
| commit_gate.py | - | Y |
| session_gate.py | - | Y |

## cleanup_boards.py (SessionStart, all enforcement levels)

Runs at session start. Archives old done tasks, trims activity log, cleans stale sessions, and
resets the per-project `review_order` rows (looping over projects).
Outputs `ONBOARDING_STATUS: not_started|interrupted (phase N)|complete` for Claude to read.
Also emits the workspace state lines for Claude to read:
- `ENFORCEMENT: full|minimal` — the workspace enforcement level
- `ACTIVE_PROJECT: <slug>` — the current active-project pointer
- `PROJECTS: <slug>, <slug>, ...` — the registered projects

## guard_boards.py (PreToolUse Edit|Write, all enforcement levels)

Blocks direct edits to auto-generated files:
- `project/board-snapshot.md` (generated at session end)
- `docs/constitution/*.md` (generated from SQLite)

## track_modifications.py (PostToolUse, all enforcement levels)

Tracks file modifications and MCP tool calls in SQLite. Also maps each edited path to its project
and updates the workspace-global active-project pointer when the edited files move to a different
project.

## commit_quality.py (PreToolUse Bash, all enforcement levels)

Basic git commit quality checks that run at every enforcement level:
1. Build verification (from project-config.json build_command)
2. Conventional commit message format
3. No Claude/Anthropic branding

## commit_gate.py (PreToolUse Bash, full enforcement only)

Review and task enforcement for git commits. Only registered when `enforcement` is `full`.
The session's modified files are grouped by resolved project, and each project's `review_order`
is enforced independently (finishing one project's reviews does not unblock a commit that also
touches another project). Per project that has changes:
4. Routing freshness (refresh_doc_routing + refresh_code_routing)
5. Code review (critical_issues == 0)
6. Doc review (unresolved_issues == 0)
7. Security review completed
8. Task validated (validate_task called before commit)
9. Tests acknowledged

Includes defense-in-depth: if registered under `minimal` enforcement by mistake, exits early.

## constitution_watch.py (FileChanged, docs/constitution/*.md, all enforcement levels)

Monitors constitution article files for external edits. Logs a warning to stderr if a constitution
markdown file is modified outside MCP tools (which would cause drift from SQLite).
Does not block — just warns.

## session_gate.py (Stop, full enforcement only)

Validates enforcement rules when source files were modified. Modified files are grouped by
project, and the checks run per project that has changes:
1. `task_started` -- start_task was called
2. `code_reviewed` -- done, critical_issues == 0
3. `doc_reviewed` -- done
4. `security_reviewed` -- done
5. `tests_acknowledged` -- done

`task_validated` is intentionally **not** gated here. Validation requires the user to re-test and
confirm, which cannot happen during a Stop-hook continuation -- gating it on Stop caused an
infinite loop (the agent parked waiting for the user, the hook re-invoked it with nothing to do).
Validation is enforced at commit time by `commit_gate.py` (Check 8) instead, which is independent
of Stop. As a further backstop, the hook honors `stop_hook_active`: if it is already inside a
Stop-hook continuation it generates the snapshot and yields rather than blocking again.

After all checks pass: generates `project/board-snapshot.md` with Mermaid charts.
Includes defense-in-depth: if registered under `minimal` enforcement by mistake, generates snapshot and exits early.
