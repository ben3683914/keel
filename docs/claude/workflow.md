# Workflow

## Task Boards

Tasks move through a pipeline managed by MCP tools:

```
todo  -->  working  -->  testing  -->  done
              |                         |
           freezer                   archive/
              |
            trash
```

Direct editing of board state is blocked by hooks — all changes go through the `task-manager` MCP server.
Board state lives in SQLite (`claude.db`). A snapshot (`project/board-snapshot.md`) is auto-generated at session end.

## Task Lifecycle

1. **Create task**: `create_task` on task-manager (auto-assigns T-/B-/S- prefix)
2. **Start task**: `start_task` moves to working board -- call this when user selects a task
3. **Load context**: Call `get_relevant_docs` with the task description — loads relevant docs and injects constitution articles. Do this before any design or implementation work.
4. **Design** (required for new features/systems): If the task introduces a new system, API, or significant behavior change, follow this three-step sequence — do not skip or collapse steps:
   a. **Iterate first.** Ask design questions one at a time via `AskUserQuestion`. Each answer may change what you ask next. Continue until scope, shape, and trade-offs are agreed. Do NOT call `write_doc` on `docs/features/` during this phase. `EnterPlanMode` is an option if you want a scratchpad for the emerging design.
   b. **Then write** the design doc in `docs/features/` via `write_doc`, reflecting what was agreed in (a). Mark genuinely undecided items `[Pending]`.
   c. **Then present** the written doc and ask for explicit go-ahead before any implementation.
   Writing the doc before (a) concludes is rubber-stamping — a constitution violation. Partial edits to existing docs use Edit directly. To remove a doc use `delete_doc`; to remove a source file use `delete_module` — never bare Bash rm for these. Quick fixes and hotfixes are exempt from the design gate.
5. **Implement**: Get explicit go-ahead, then delegate to agent teams
6. **Self-verify**: Audit implementation against the plan — all items completed, no placeholder code, tests cover new code
7. **Code review**: Spawn code-reviewer agent (`model: "sonnet"`) -> `acknowledge_code_review`
8. **Doc review**: Spawn docs-reviewer agent (`model: "sonnet"`) -> `acknowledge_review`
9. **Security review**: Spawn security-reviewer agent (`model: "sonnet"`) -> `acknowledge_security_review`
10. **Tests**: Spawn test-runner agent (`model: "sonnet"`) -> `acknowledge_tests`
11. **Move to testing**: `move_to_testing` for user verification
12. **Validate**: User confirms it works -> `validate_task` moves to done
13. **Commit**: `git commit` (commit_gate validates all steps)
14. Board snapshot auto-generated at session end

## When to Call `get_relevant_docs`

`get_relevant_docs` is not just a task-lifecycle step — it's the first-line retrieval tool for any conceptual question about the codebase. It finds topic-relevant docs AND injects constitution articles in the same call.

**Call it when:**
- Starting a task (step 3 of the lifecycle above)
- The user asks how a system works, what something does, or for an architecture/API explanation
- Before reading source to *explain* behavior (as opposed to verifying a specific line or signature)
- Re-orienting after a long session or context compaction

**Don't require it for:**
- Mechanical lookups (show me line 50, confirm a signature, grep-style verification)
- When the user names a specific file and asks to read it
- Quick edits where the target is already known

Source files are the fallback when docs are missing, stale, or don't cover the question — not the default starting point. Skipping `get_relevant_docs` on a conceptual question bypasses the routing layer and misses context that lives in feature docs and constitution articles.

## Review Order

Reviews are enforced in order: code -> docs -> security -> tests.
Each acknowledgment tool checks that the previous step is complete.
Review state is **per project** — stored in the SQLite `review_order` table keyed by project, and
applied to the active project (reset at session start). When a commit spans more than one project,
each project's review pipeline is enforced independently; completing one project's reviews does not
unblock a commit that also touches another.

## Commit Checklist

Before committing:
- [ ] Task started (`start_task`)
- [ ] Code review passed (no critical issues)
- [ ] Docs reviewed (no unresolved issues)
- [ ] Security review completed
- [ ] Task validated (`validate_task` -- user confirmed it works)
- [ ] Tests acknowledged
- [ ] Build passes
- [ ] Routing configs refreshed (if source modified)
- [ ] `.claude/claude.db` staged — it holds all project state and is intentionally tracked in git; never skip it

## Constitution

- Check constitution articles before designing new features
- Proactively propose articles for significant design decisions
- Violations are flagged during code review and design
- The constitution is **two-tier**: workspace articles apply to every project, and each project may
  add its own. The effective set for a project is the union (workspace ∪ project), numbered per tier.
  Workspace-tier markdown lives in `docs/constitution/`; a project's articles live in
  `<project.path>/docs/constitution/`.
- Compact constitution (workspace + active project) is injected into every doc tool response (article number + title + rule)
- Full articles loaded at session start via `get_startup_docs`
- Articles have categories (design, documentation, workflow, collaboration, general) for filtered injection

## First-Run Onboarding

Triggered by `ONBOARDING_STATUS` in the SessionStart hook output (not a direct DB query).
The onboarding interview uses `AskUserQuestion` for each question — **one question per call, asked sequentially; never batch them or list the upcoming questions in chat**. No task-manager or docs-manager MCP tools needed. Works at any enforcement level.

1. Tour-or-setup choice (offer the tutorial, or proceed to setup)
2. New project or existing codebase?
3. Workspace shape selection → config interview → create the project folder(s) via `new_project.py` → `assemble.py` (generates CLAUDE.md + settings.json) → README
4. **New** → start fresh in the created `./<slug>/` folder. **Existing** → tell the user to drop their code into the created `./<slug>/` folder, then run `/document-project` to document it.
5. After completion: config updated, baseline snapshot created, flag set

**Every shape creates at least one real project in its own `./<slug>/` subfolder** — single (1 project, full enforcement), scratch (1 project, minimal), multi (N projects, full). The `workspace` row is the umbrella only; you never work on it directly and no project ever lives at the repo root.

### Onboarding Questions

**Ask exactly ONE question per `AskUserQuestion` call, then wait for the answer before asking the next.** `AskUserQuestion` can technically hold up to four questions, but onboarding asks **one per call**. The table below is *your* private sequencing checklist, NOT a menu to show the user: do **not** paste it into chat, do **not** enumerate the upcoming questions, and do **not** invite the user to "answer them all at once." Each answer can change what you ask next (e.g. the tech-stack answer shapes the testing and source-config questions), which only works one question at a time. One question → one answer → next.

**First question — Tour or set up? (ALWAYS first):** Before anything else, offer a simple two-way choice:

> Welcome! Would you like to **set up your project** now, or take a quick **tour of the template** first (you can ask it anything)?
> - **Set up my project** — proceed to setup (Question 0 below).
> - **Take the tour** — an interactive walkthrough of how the template works.

If **Take the tour** is selected, run the tutorial by **reading and following `.claude/skills/tutorial/SKILL.md`** (the same content as `/tutorial`; see Tutorial Mode below) — the tutorial skill is user-invocation-only, so follow that file rather than invoking it as a skill. It ends by offering to start setup, at which point continue with setup below. Do **not** add a "work on the template" or "look around" option here — the template-dev escape hatch is reactive-only (it activates only if the user themselves says they are working on the template).

**Setup — new project or existing codebase?** When the user chooses to set up, ask this *before* the shape question:

> Is this a brand-new project, or an existing codebase you want to bring into the template?
> - **New project** — start fresh.
> - **Existing codebase** — there's already source here to analyze.

- **Existing codebase** → run only the **light** questions (shape + project Basics: name, slug, greeting), then hand the rest to `/document-project`. Do **not** ask the Tech/Testing/Conventions questions — `/document-project` derives those from the code. Sequence: (a) ask shape and the Basics; (b) create the `./<slug>/` folder(s) via `new_project.py` (source config can start at the defaults — the skill refines them); (c) **tell the user to move/copy their existing code into that folder** and confirm when done; (d) **read and follow `.claude/skills/document-project/SKILL.md`** (the `/document-project` skill — user-invocation-only, so follow the file rather than invoking it) scoped to the `./<slug>/` folder — it detects the stack, sets `source_roots`/`source_extensions` on the entry, generates baseline docs, proposes constitution articles, and marks onboarding complete; (e) finish with the wrap-up (Post-Interview step 8). Skip the greenfield README-fill (step 3) — the code's own README stays. For a **multi** existing workspace, create every folder first, have the user place each codebase, then document each.
- **New project** → continue with the questions below.

**Question 0 — Workspace shape (new projects only):**

> How should this workspace be set up?
> - **Single project** — Full enforcement. Reviews, docs, constitution, and task tracking active. Your work lives in one project folder (`./<slug>/`). This is the standard choice for a focused project. Adding another project later via `/add-project` turns it into a multi-project workspace.
> - **Multi-project** — Full enforcement, with several projects scoped independently (separate boards, status, health, routing, and a per-project constitution tier on top of the workspace tier). Each lives in its own `./<slug>/` folder; gathered now and can be added later via `/add-project`.
> - **Scratch** — Minimal enforcement. Tools available but optional. No reviews, no doc enforcement. Good for experiments, prototypes, learning. Still one project folder (`./<slug>/`), just light-touch.

Record the choice immediately: `update_onboarding(field="project_mode", value="single|multi|scratch")`
(the `onboarding` table field name is unchanged; the value captures the chosen shape). The shape maps to
config at completion: **single** → `enforcement: "full"`, one `projects[]` entry; **multi** →
`enforcement: "full"`, `projects[]` populated from the gathered projects; **scratch** →
`enforcement: "minimal"`, one `projects[]` entry. **Every shape produces at least one real
`projects[]` entry created via `new_project.py`** — the only differences are enforcement and how many
projects. The `workspace` row stays the umbrella (constitution tier + cross-cutting board + fallback);
no shape works on it directly.

**Remaining questions by shape:**

| # | Group | Question | Scratch | Single | Multi |
|---|-------|----------|:---:|:---:|:---:|
| 1 | Basics | **Project name** — What's the workspace called? | Y | Y | Y |
| 2 | Basics | **Session greeting** — What greeting at session start? (skip for none) | Y | Y | Y |
| 3 | Basics | **Project purpose** — What does it do? (one sentence) | - | Y | Y |
| 4 | Tech | **Tech stack** — Languages, frameworks, tools? | - | Y | Y |
| 5 | Tech | **Testing approach** — What test framework and strategy? | - | Y | Y |
| 6 | Tech | **Coding conventions** — Specific style rules? | - | Y | Y |
| 7 | Git | **Git repository** — Fresh start (default), keep as-is, or connect to a remote? | Y | Y | Y |
| 8 | Git | **Branching strategy** — trunk, gitflow, feature branches, etc.? | - | Y | Y |
| 9 | Git | **Commit conventions** — Any message format? (default `type: description`) | - | Y | Y |
| 10 | Process | **Goals** — Current goals or milestones? | - | Y | Y |
| 11 | Process | **Review strictness** — strict, moderate, or light? | - | Y | Y |
| 12 | Process | **Deployment strategy** — Manual, CI/CD, etc.? | - | Y | Y |
| 13 | Process | **Team structure** — Solo dev or team? | - | Y | Y |

Ask the groups in order (**Basics → Tech → Git → Process**) so related questions stay together — but still one question per `AskUserQuestion` call. For the **Git repository** question, present **Fresh start** as the default/recommended option (it re-initializes git history for the new project, discarding the template's history); offer "keep as-is" and "connect to a remote" as the alternatives.

For **single** and **scratch**, one project is built — derive its `slug` (slugified project
name) and folder (`./<slug>/`) from the Basics answers. For **multi**, also gather each project
(its name, slug/path, and tech stack) so a `projects[]` entry can be built per project. In all
cases this is the same data `/add-project` collects and `new_project.py` consumes.

**Scratch defaults** (not asked, applied automatically):
- Commit conventions: `type: description` (conventional commits)
- Review strictness: none
- Testing approach: none

**Source configuration** (derived from the tech-stack answer under full enforcement, not asked) —
passed to `new_project.py` as the project entry's own keys, **relative to the project folder**:
- `--source-roots src` (the default; the project's code lives under `./<slug>/src/`).
- `--source-extensions` from the inferred language (e.g., Python → `.py .pyi`; Terraform → `.tf .tfvars .hcl`).
- `exclude_dirs` stays the standard default list (`docs`, `tests`, `node_modules`, `.venv`, build outputs, etc.) — the helper does not override it.
- Every `projects[]` entry carries its own `source_roots` / `source_extensions` / `test_command`; the workspace-level keys are left alone.
- User can edit any of these manually after onboarding if defaults miss the mark.
- Scratch still creates the folder + entry, but routing is light-touch under minimal enforcement.

### Post-Interview Steps

**Order matters.** Write config and run `assemble.py` *before* any `update_onboarding`
call. A freshly-cloned template ships `template_dev: true`, and the template-dev guard
blocks `update_onboarding` (and other lifecycle writes) while that flag is set.
`assemble.py` flips `template_dev → false` once `enforcement` is written to config, which
releases the guard. Calling `update_onboarding` first would be blocked — the flag has not
flipped yet. (Scaffold-only maintainers who never write `enforcement` stay in dev mode, so
the guardrail is unchanged for them.)

1. **Create each project via the shared helper** — for every project (one for single/scratch, N for multi):
   ```
   .claude/venv/bin/python .claude/scripts/new_project.py \
     --slug <slug> --name "<name>" --path <slug> \
     --description "<purpose>" \
     --source-roots src --source-extensions <.ext ...> \
     --test-command "<command>"
   ```
   This creates `./<slug>/` with `docs/index.md` + a stub `README.md`, appends the `projects[]`
   entry, and refreshes routing. Then write `enforcement` to `project-config.json` (per the shape
   mapping above). Do **not** hand-edit `projects[]` — the helper owns it.
2. **Run `python .claude/scripts/assemble.py`** to generate CLAUDE.md + settings.json (mode is derived from `enforcement`: `minimal` → scratchpad assembly, `full` → project assembly). This also flips `template_dev → false`, releasing the guard.
3. **Fill the READMEs** (skip for the existing-codebase path — that project's README comes with its code):
   - **Project README** (`./<slug>/README.md`, stubbed by the helper): fill from the gathered answers — set the `# <name>` title, replace the description line with the project purpose, and fill the **Quick Reference** Build / Run / Test from `build_command` / `test_command` (or infer from the tech stack; `TBD` only if genuinely unknown). This is the project's real front page.
   - **Root `README.md`** (the workspace overview): set its title to the workspace/project name and a one-line summary noting the project lives in `./<slug>/` (for multi, list the project folders). The root README describes the *workspace*, not the project internals. Both are project-local — the engine never overwrites them. (Scratch: only the project name is known, so just set titles and leave the rest of the placeholders.)
4. Store all answers via `update_onboarding` (now permitted — the guard has been released)
5. Execute git setup based on git repository answer (see below)
6. Mark onboarding complete: `update_onboarding(field="complete", value="1")`
7. **Run the session start checklist**: call `get_startup_docs` → `get_project_status` → `check_code_health` → `check_doc_health` (loads state for the resumed session).
8. **Wrap-up message.** Onboarding is complete and the setup is saved in `claude.db`. Recommend the user run **`/clear`** now to start their first task with a clean context — *nothing is lost; a fresh session resumes exactly here.* Mention they can run **`/tutorial`** anytime to learn how the template works, and that sessions should be ended with **`/exit`** (not force-closed) so session-end housekeeping (e.g. the board snapshot) runs. Prefer this over diving straight into a task — a clean context for the first real piece of work beats one full of onboarding chatter.

**Documentation compliance during onboarding**: any docs written during or after onboarding must include the Article 004 metadata header:
```
> **Version:** 0.1.0 | **Last Updated:** YYYY-MM-DD | **Status:** Draft
```
For a multi-project workspace: after creating the sub-projects, update `docs/core/architecture.md` to reference each project in the Sub-Documents table.

### Post-Onboarding Git Setup

Execute based on the git repository answer. A freshly-cloned template **always** arrives with the template's own git history, and often with uncommitted edits to template internals — this is **expected**, not a problem to flag. Do **not** stop to ask things like "this repo has real git history and uncommitted edits, how should I proceed?" — the chosen option below already decides that.

- **Keep as-is** — No action. Project starts from the template baseline commit (the template's history is retained intentionally).
- **Connect to remote** — Ask for remote URL, then run `git remote add origin <url>`. Offer to push.
- **Fresh start** (default) — The new project owns its own history, so discarding the template's is the entire point of this option. Reinitialize **without further confirmation**: `rm -rf .git && git init && git add -A && git commit -m "chore: initial commit"`. This intentionally wipes the template's git history and folds everything currently in the working tree (including any uncommitted template edits) into the new project's first commit.

### Tutorial Mode

When **tutorial** is selected, run the interactive walkthrough defined in the `/tutorial` skill — **read and follow `.claude/skills/tutorial/SKILL.md`** (the same tour is available anytime via `/tutorial`). Key principles (the skill spells them out in full):
- **Don't scan the repo.** The tour is curated in the skill; read a specific file only if the user asks something it doesn't cover.
- First ask whether they want a **guided tour** or to **jump into the topic menu**.
- Keep answers brief and conversational; go deeper only on request. Give the **design-first** and **context-management** points extra emphasis.
- The user can ask anything, jump around, or bail at any time.
- At the end, offer to start the real onboarding interview with a chosen shape (single / multi / scratch), asking one question at a time.

## Rules

These rules apply at **every enforcement level** unless noted:

- Do not push to remote without user confirmation
- Do not include Co-Authored-By, Claude, or Anthropic branding in commits
- Use conventional commit format: `type: description`

**Full enforcement only:**

- Do not edit auto-generated files directly (board-snapshot, constitution articles)
- Do not edit source files without starting a task first
- Always delegate implementation to agent teams
- Run reviews in order: code -> docs -> security -> tests (per project; a commit spanning projects must satisfy each project's pipeline)

**Minimal enforcement:**

- Task tracking is available but optional
- Reviews are available but optional
- Documentation is not enforced
- Constitution articles are not injected into tool responses
