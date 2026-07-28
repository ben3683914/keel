---
name: document-project
description: Generate baseline documentation, routing, and registration for the code in a project folder — for an existing codebase brought into the template
disable-model-invocation: true
argument-hint: "[path]"
---

Document the code sitting in a project folder: discover its structure, ensure it is
registered as a `projects[]` entry, and generate the baseline documentation that the
routing, constitution, and review systems need to be useful.

**Every project lives in its own `./<slug>/` subfolder** — never at the repo root.
The normal flow for an existing codebase: onboarding creates the project folder and
registers it, the user drops their code into that folder, then runs `/document-project`
(optionally `/document-project <slug-or-path>` to scope to one folder). This works for
a **single project** (one folder) and a **multi-project** workspace (several folders)
by exactly the same path — single is just "one project." This IS the onboarding path
for a pre-existing repo — by the end, onboarding is marked complete.

**You are the orchestrator.** Delegate code analysis to agent teams via the Task
tool (they read code and return findings); YOU perform every MCP call (`write_doc`,
routing, constitution, tasks, onboarding) and every config edit. Sub-agents cannot
call MCP tools.

Argument: an optional sub-path to limit scope (e.g. `/document-project apps/web`).
With no argument, document the whole repo.

**Resumable — track progress in the DB.** A large repo's analysis can span more than
one session. At the start call `update_onboarding(field="is_existing_repo", value=1)`,
and as you finish each phase call `update_onboarding(field="current_phase", value=N)`
(A=1 … E=5). Session-start then reports `interrupted (phase N)` and offers to resume
right here, so a `/clear` mid-analysis loses nothing.

---

## Phase A — Discover the structure (then CONFIRM with the user)

1. Detect candidate projects by scanning for build/manifest markers, NOT just by
   eyeballing folders:
   - Per-language: `package.json`, `pyproject.toml` / `setup.py` / `requirements.txt` /
     `Pipfile`, `go.mod`, `Cargo.toml`, `pom.xml` / `build.gradle(.kts)`, `*.csproj` /
     `*.fsproj`, `Gemfile`, `composer.json`, `mix.exs`, `pubspec.yaml`, `Package.swift`,
     `deno.json`, `CMakeLists.txt`, `*.tf`, etc.
   - Monorepo signals (strong multi-project markers): `pnpm-workspace.yaml`,
     `lerna.json`, `nx.json`, `turbo.json`, `go.work`, or a `[workspace]` table in a
     root `Cargo.toml`.
   - **Exclude dependency/build dirs** from the glob (`node_modules`, `vendor`, `.venv`,
     `venv`, `dist`, `build`, `target`, `.git`, `__pycache__`) so you never register a
     dependency's manifest as a project.
   - Use `Glob` for the markers and note their directories. If the project is already
     registered (the onboarding flow created the folder and `projects[]` entry before
     the user dropped code in), just document the registered folder(s); scan **inside**
     each project folder for its stack. If invoked standalone on unregistered code,
     detect the project folder(s) under the repo root — **one** subfolder signals a
     single project; **several** signal a multi-project workspace. If a `[path]`
     argument is given, scope to that one folder.
   - **No markers found?** Don't invent a stack. Ask the user which folder holds the
     project and its source directory(ies) and language, so `source_roots` /
     `source_extensions` can still be set correctly.
2. For each candidate, infer: a `slug` (lowercase, url-safe), `name`, `path`,
   the `source_roots` and `source_extensions` (from the stack), and the
   `test_command` (from the manifest's scripts/config). Also infer the project's
   **purpose** from its README / manifest description / directory name (used in Phase E).
3. **Present the detected shape to the user with `AskUserQuestion`** and let them
   correct it before anything is written:
   - single vs multi, and the project list (add/remove/rename, fix paths).
   - `enforcement`: `full` (reviews + constitution + tasks enforced) or `minimal`
     (a scratch workspace — light-touch). Default `full`.
   Do not proceed to Phase B until the project list is confirmed.

## Phase B — Register the project(s)

Every confirmed project (whether the workspace has one folder or several) is registered
the **same way** — there is no single-vs-multi split, and nothing is ever left on the
`workspace` row. For each confirmed project **that is not already in `projects[]`**, run
the shared helper (the same path `/add-project` and onboarding use):

```
.claude/venv/bin/python .claude/scripts/new_project.py \
  --slug <slug> --name "<name>" --path <folder> \
  --description "<purpose>" \
  --source-roots <root> [<root> ...] \
  --source-extensions .ext [.ext ...] \
  --test-command "<command>" \
  --no-scaffold
```

Use `--no-scaffold` here: the folder already exists and holds the user's code, so the
helper only registers the `projects[]` entry (and won't clobber an existing README or
docs). A project already registered by onboarding needs no re-registration — skip it.

- Set `enforcement` in config to the confirmed value.
- Run `.claude/venv/bin/python .claude/scripts/assemble.py` to refresh CLAUDE.md/settings for the
  chosen enforcement.

## Phase C — Document each project (the core)

For EACH project folder, in turn:

1. **Delegate analysis to agent team(s)** via the Task tool. For a large codebase,
   fan out several agents by area (e.g. one per top-level package/layer). Give each
   agent the project path and ask it to return STRUCTURED findings (raw data, not
   prose for a human):
   - purpose and high-level architecture (entry points, layers, data flow);
   - the key modules/files and each one's responsibility;
   - public interfaces / APIs / exported surfaces;
   - observed conventions (naming, error handling, testing, structure);
   - notable patterns, invariants, and any obvious risks or tech debt.
2. **Synthesize** the agents' findings and **write docs via `write_doc`** into the
   project's doc root (`<path>/docs/`):
   - `index.md` — overview + a map of the docs and the codebase;
   - `architecture.md` — structure, layers, data flow, entry points;
   - `conventions.md` — the observed conventions (so future work matches them);
   - additional per-area docs when the codebase is large enough to warrant them.
   Keep each doc focused and link related docs. Prefer several modular docs over one
   giant file (the routing system rewards modularity).
3. After writing a project's docs, call `refresh_doc_routing` and
   `refresh_code_routing` so the new docs and that project's source are indexed
   (this also syncs the project into the routing DB).

Scope the analysis to the active project — when you begin working in a sub-project's
files, the active project follows; responses echo `[project: <slug>]` so you can
confirm you're documenting the right one. Pass `project=<slug>` to MCP calls to be
explicit.

## Phase D — Seed governance (propose, don't impose)

1. From the conventions and invariants the analysis surfaced, **propose constitution
   articles** with `propose_article` — workspace-tier (applies to every project) for
   cross-cutting rules, project-tier for project-specific ones. Present each to the
   user and only `ratify_article` the ones they approve. Do not over-generate.
2. Create `create_task` entries for the gaps the analysis found (undocumented areas,
   untested modules, risky patterns) so the work is tracked rather than lost.

## Phase E — Finalize

1. Mark onboarding complete: set the project name/purpose (inferred in Phase A,
   confirmed with the user) and `complete=1` via `update_onboarding` (documenting an
   existing repo IS its onboarding). Set a `greeting` in config if useful.
2. Call `get_project_status` (and `project='all'` for a multi-project rollup) to
   show the resulting board/phase per project.
3. **Summarize** what was created: the registered projects, the docs written per
   project, articles proposed/ratified, and tasks opened — so the user sees the
   coverage at a glance.

## Guardrails

- CONFIRM the project structure (Phase A) before writing anything — never auto-commit
  a structure the user hasn't seen.
- Don't fabricate. If the analysis can't determine something, write what is known and
  open a task for the gap rather than inventing detail.
- Large repos: bound each analysis agent's scope and `log`/report what was and wasn't
  covered, so partial coverage never reads as complete.
- You write docs through `write_doc`, not by editing files under `docs/` directly
  (the routing system tracks docs written through the MCP tool).
- **Respect what's already there.** If the repo already has docs or a README, augment
  and fill gaps — do NOT overwrite the project's own files. The greenfield README-fill
  step does not apply to an existing repo (its README is real); leave it alone unless
  the user asks otherwise.
- Follow the constitution's doc rules when writing: Mermaid for diagrams (Article 007),
  the doc size limit (Article 008), and the metadata header (Article 004). Prefer
  several modular docs over one giant file.
