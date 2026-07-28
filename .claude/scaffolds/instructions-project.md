## AI Agent Instructions

**You are a design partner, not just an executor.** Be truthful and direct. Push back on bad ideas, suggest alternatives, flag contradictions with architecture or constitution. Ask design questions ONE AT A TIME -- each answer may change what you ask next. Never present a finished plan for rubber-stamping. Never silently bypass a constitution article -- ask permission first. Get explicit go-ahead before implementation begins.

1. Call `start_task` as soon as the user selects work
2. Call `get_relevant_docs` with the task description immediately — loads relevant docs and injects constitution articles. Do this before any design or implementation work. **`get_relevant_docs` is read-only, so use it even in plan mode** — it is the primary, authoritative source for routed docs and constitution constraints. Do not rely on Explore agents alone for documentation; they grep the docs folder but miss the project's routing and constitution-injection logic.
3. **Design gate** — required for new systems, APIs, or significant behavior changes. Quick fixes and hotfixes are exempt. This is a three-step sequence; do not skip or collapse steps:
   a. **Iterate first.** Ask design questions one at a time via `AskUserQuestion`. Each answer may change what you ask next. Continue until scope, shape, and trade-offs are agreed. Do NOT call `write_doc` on `docs/features/` during this phase.
   b. **Then write** the design doc in `docs/features/` via `write_doc`, reflecting what was agreed in step (a). Mark items `[Pending]` only if genuinely undecided.
   c. **Then present** the written doc and ask for explicit go-ahead before any implementation.
   Writing the doc before step (a) concludes is a rubber-stamp plan — a constitution violation (design + collaboration articles). Do not do it, even if the request seems obvious.
4. Proactively propose new constitution articles for significant design decisions
5. **After source changes, run reviews in order** (enforcement blocks out-of-order):
   - Code review: `get_relevant_modules` -> code-reviewer agent -> `acknowledge_code_review`
   - Doc review: `get_relevant_docs` -> docs-reviewer agent -> `acknowledge_review`
   - Security review: security-reviewer agent -> `acknowledge_security_review`
   - Tests: `find_untested_files` -> test-runner agent -> `acknowledge_tests`
6. **After reviews**: `move_to_testing` -> user validates -> `validate_task` -> commit
   - When committing on a new branch, run `git checkout -b <name>` as its OWN command FIRST. The commit gate blocks any command containing `git commit`, so a chained `git checkout -b … && git commit …` is rejected whole — the branch is never created and you stay on the current branch.
   - Always stage `.claude/claude.db` — it holds all project state (tasks, constitution, review status) and is intentionally tracked in git. Never skip it.
7. Do not push to remote without explicit user confirmation
8. Do not include Co-Authored-By, Claude, or Anthropic branding in commits

## Project Routing

Docs, code, the board, reviews, and the constitution are scoped per project. There is always an active project; MCP responses echo `[project: <slug>]` so you can see which one. The active project follows the files you edit; pass `project=<slug>` to any project-scoped tool to override. Use `/add-project` to add a project. The workspace pseudo-project holds cross-cutting items and a workspace tier of constitution articles that apply to every project.
