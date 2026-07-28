---
name: add-project
description: Add a project to the workspace for scoped doc/code routing, boards, status, and constitution
disable-model-invocation: true
argument-hint: "[slug] [path]"
---

Add a project to the workspace. This scopes documentation routing, code routing,
the task board, project status, reviews, health, and the constitution to the new
project's directory.

Adding a project is **always valid** — there is no mode prerequisite. A single-project
workspace already has one `projects[]` entry; `/add-project` simply appends another,
making it multi-project. Each subsequent call appends one more. (There is no special
"single" state to migrate from — single is just "one project.")

## Steps

1. **Gather info** (from arguments or by asking):
   - `slug` — the project's identity key, lowercase and url-safe (e.g., "frontend",
     "api", "infra"). This is what `project=<slug>` arguments and the `[project: <slug>]`
     echo use, so it must be stable and unique.
   - `name` — display name (e.g., "Web Frontend"). Can differ from the slug.
   - `path` — root directory relative to repo root (e.g., "apps/web", "services/api").
   - `description` — short summary (e.g., "React web application").
   - `source_roots` — directories under `path` that hold source (e.g., `["src"]`).
   - `source_extensions` — extensions code routing should index (e.g., `[".ts", ".tsx"]`).
   - `test_command` — how to run this project's tests (may be left empty).

2. **Create + register via the shared helper** — this is the SAME code path onboarding
   uses for every project, so add-project and onboarding never drift:
   ```
   .claude/venv/bin/python .claude/scripts/new_project.py \
     --slug <slug> --name "<name>" [--path <path>] \
     --description "<description>" \
     --source-roots <root> [<root> ...] \
     --source-extensions .ext [.ext ...] \
     --test-command "<command>"
   ```
   The helper: validates the slug/path (rejects duplicates and the repo root — every
   project must live in its own subfolder), creates `<path>/` with a `docs/index.md`
   and a stub `README.md` (never clobbering existing files), appends the self-contained
   `projects[]` entry (each carries its own `source_roots` / `source_extensions` /
   `test_command` — the workspace-level keys are left untouched), and refreshes doc +
   code routing so the new folder is indexed. `--path` defaults to the slug. Pass
   `--no-scaffold` only when the folder already exists and is populated (e.g. an
   existing codebase the user dropped in).

3. **Re-assemble**:
   - Run `.claude/venv/bin/python .claude/scripts/assemble.py` to update CLAUDE.md if needed.

4. **Confirm**: Report what was added and the current `projects[]` list (the helper
   prints both as JSON on success).
