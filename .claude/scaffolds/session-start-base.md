## Session Start

**First**, check if `.claude/venv/bin/python` exists. If not, run `bash setup.sh` to bootstrap the Python venv and MCP dependencies. MCP servers will not work without it.

**Then** read the SessionStart hook output:
- If `GREETING:` is present — display it to the user immediately, before anything else
- Read `ONBOARDING_STATUS`:
  - `not_started` → Start onboarding immediately by offering a simple **two-way choice — set up the project now, or take a quick tour first** (the tour means reading and following `.claude/skills/tutorial/SKILL.md` (the same content as `/tutorial`), which ends by offering to start setup). Do **not** add a "work on the template" or "look around" option — the template-dev escape hatch stays reactive-only (below). After "set up", ask whether it's a new project or an existing codebase — existing routes to the `/document-project` path; new continues with the workspace-shape question (see docs/claude/workflow.md). Ask with `AskUserQuestion` **one question at a time — exactly one question per call; never batch questions or list the remaining ones in chat.** Works in any mode including plan mode.
  - `interrupted (phase N)` → Offer to resume onboarding analysis from where it left off.
  - `complete` → Run the session start checklist below. **Do this before responding to any user message.**

**Onboarding does NOT require task-manager or docs-manager MCP tools.** Use `AskUserQuestion` for each question — one at a time (one question per call; wait for each answer before asking the next). Store answers via MCP only at the end.

**Template-development escape hatch (reactive only — never offer it).** This exists for the template maintainer, not end users: **never** surface it as a choice, list it as an option, or ask whether the user wants to work on the template. It activates **only** when the user *themselves*, unprompted, states they are working on the template itself (or explicitly asks to skip onboarding). When that happens, acknowledge and proceed without running the interview, and do NOT call `update_onboarding` to mark `complete=1` — `.claude/claude.db` is tracked in git, and any mutation ships to every downstream copy of the template, which would cause new projects cloned from it to skip their own onboarding.
