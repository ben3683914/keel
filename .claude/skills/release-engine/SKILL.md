---
name: release-engine
description: Generate a new version entry for the engine-update manifest from current changes
disable-model-invocation: true
argument-hint: "[version]"
---

Helps the template maintainer create a patch entry for `engine-update.py`. Detects changed files, classifies them, checks for DB migrations, and writes the manifest entry.

## Semver Rules

The scan auto-determines the version bump level based on the git diff:

| Level | When | Example |
|-------|------|---------|
| **Major** (X.0.0) | Reserved for breaking changes that require manual intervention | Removing engine files consumers depend on, incompatible DB schema changes |
| **Minor** (0.X.0) | New features, new files, DB schema additions, hybrid file changes | New skill, new hook, new DB column, settings.json merge needed |
| **Patch** (0.0.X) | Bug fixes, tweaks to existing engine files, doc updates | Fix in commit_gate.py, updated mcp-tools.md |

The scan output includes `suggested_version`, `bump_level`, and `bump_reason`. Present these to the user — they can override if they disagree.

## Steps

0. **Offer to run `/prep-release` first.** Ask the user via `AskUserQuestion` whether to run `/prep-release` now — default to **yes**, since it almost always immediately precedes a release. It exports the constitution scaffold to `.claude/scaffolds/constitution.json` and wipes dev-session DB state; without it the scaffold is stale and consumers won't receive the latest articles. Skip only if the user confirms it was already run this session. If yes, run that flow to completion before continuing here.

1. **Detect changes**: Run `.claude/venv/bin/python .claude/scripts/shared/patch_builder.py --scan` to get a JSON report of:
   - Changed files classified by layer (engine, engine_docs, hybrid, constitution, project, unknown)
   - Whether `db.py` schema changed (potential migration needed)
   - Current template version from DB
   - Suggested next version with bump level and reason (or use `$ARGUMENTS` if provided)

2. **Review classification**: Present the file classification to the user:
   - Engine files (will overwrite on patch)
   - Engine docs (will overwrite on patch)
   - Hybrid files (will merge on patch)
   - Project files (will be SKIPPED — never patched)
   - Unknown files (ask user to classify)
   
   Ask if the classification looks correct. Let the user reclassify or exclude files.

3. **Check for migrations**: If `db.py` was modified, ask the user:
   - Was the schema changed (new table, new column)?
   - If yes, help draft the migration SQL and a migration key name
   - If no, skip migrations

4. **Draft version entry**: Show the user the complete VERSIONS dict entry that will be added, including:
   - Version number
   - Description (ask user for a one-line summary)
   - Migrations list
   - Changes by category with action types

5. **Check existing manifest**: Run `.claude/venv/bin/python .claude/scripts/shared/patch_builder.py --check` to verify:
   - No duplicate version numbers
   - All referenced migration keys exist in MIGRATIONS dict
   - No files listed that don't actually exist

6. **Write to manifest**: After user approval, run `.claude/venv/bin/python .claude/scripts/shared/patch_builder.py --write --version <ver> --data <json>` to insert the entry into `engine-update.py`. This also bumps the DB's `template_meta.template_version` to `<ver>`.

7. **Sync the version sources**: `--write` updates the DB but NOT `.claude/project-config.json`, and the scaffold embeds whatever version was in project-config when `/prep-release` exported it. Set `template_version` in `.claude/project-config.json` to `<ver>`, then re-run `.claude/venv/bin/python .claude/scripts/shared/constitution_export.py` so the scaffold embeds `<ver>`. After this, all three agree: project-config.json, DB `template_meta`, and the manifest entry. (Best practice: bump `project-config.json` to the intended version BEFORE `/prep-release` so the first export is already correct — this step is the catch-up if you didn't.)

8. **Commit offer**: Ask the user via AskUserQuestion if they want to commit the release.
   If yes, commit all changed files (manifest, scaffold, regenerated constitution markdown, `project-config.json`, `claude.db`). Exclude `.claude/settings.local.json` (local-only). Do not include Co-Authored-By or AI branding in the message.

9. **Tag the release**: After the release commit lands, create an annotated git tag so the version is checkout-able and releases have a clean reference point in history.
   - `git tag -a v<ver> -m "v<ver>: <one-line description>"` on the release commit.
   - Use the SAME `v<ver>` that went into the manifest and DB, so tag, manifest, and DB all agree.
   - Use annotated tags (`-a`), never lightweight — they carry the release message, tagger, and date.
   - Push via the `/push` skill (raw `git push` is denied by permissions). Because `/push` uses `--follow-tags`, pushing the branch carries the annotated release tag automatically. If the branch is already up to date or you're backfilling tags, run `.claude/venv/bin/python .claude/scripts/shared/git_push.py <remote> <branch> --tags` to push all tags.

## File Classification Rules

| Path Pattern | Layer | Action |
|---|---|---|
| `.claude/scripts/hooks/*` | engine | overwrite |
| `.claude/scripts/mcp/*` | engine | overwrite |
| `.claude/scripts/shared/*` (except `git_push.py`) | engine | overwrite |
| `.claude/scripts/engine-update.py` | engine | overwrite |
| `.claude/agents/*` | engine | overwrite |
| `.claude/skills/*/SKILL.md` | engine | overwrite |
| `.mcp.json` | engine | overwrite |
| `setup.sh` | engine | overwrite |
| `docs/claude/*` | engine_docs | overwrite |
| `.claude/settings.json` | hybrid | merge_json (deep_merge_hooks) |
| `.claude/doc-enforcement.json` | hybrid | merge_json (deep_merge_rules) |
| `CLAUDE.md` | hybrid | merge_section |
| `.gitignore` | hybrid | merge_append |
| `.gitattributes` | hybrid | merge_append |
| `docs/guides/*` | hybrid | merge_section |
| `.vscode/*` | hybrid | merge_json |
| `docs/constitution/*` | project | SKIP (auto-generated from SQLite; propagation is handled by the `constitution` category) |
| `docs/core/*` | project | SKIP |
| `docs/features/*` | project | SKIP |
| `README.md` | project | SKIP |
| `.claude/project-config.json` | project | SKIP |
| `project/*` | project | SKIP |
| `.claude/scaffolds/*` | engine | add |
| `.claude/scaffolds/constitution.json` | constitution | apply_constitution_scaffold |

## Constitution Propagation

The template's ratified articles ship to consumers via `.claude/scaffolds/constitution.json`, not via the markdown files under `docs/constitution/`. Identity is tracked by a `source_id` column on the `constitution` table:

- `template:<slug>` — shipped by the template (upserted on upgrade).
- `project:<slug>` — authored locally by a consumer (never touched).
- `NULL` — pre-1.5.0 rows; the first upgrade matches them by normalized title and adopts the template's source_id.

`action_apply_constitution_scaffold` preserves local divergence: rows with status `amended` or `revoked` are skipped and reported in the `conflicts` output. Articles `propose_article` creates are automatically namespaced based on `template_dev` in `project-config.json`.
