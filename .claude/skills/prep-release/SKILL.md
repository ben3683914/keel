---
name: prep-release
description: Reset the template's claude.db to a pristine state before tagging a distribution release
---

Strips per-session working state that accumulates during template development — leaked local file paths in `session_state`, stray `activity_log` entries, stale `code_routing` rows, any leftover `tasks` — while preserving seed data that IS the template (`constitution`, `doc_routing`, `template_meta`).

Run this before `/release-engine` when preparing a distribution tag.

## Steps

1. **Export constitution scaffold first.** Run `.claude/venv/bin/python .claude/scripts/shared/constitution_export.py --dry-run` and show the user what will be backfilled/exported. Then run it for real: `.claude/venv/bin/python .claude/scripts/shared/constitution_export.py`. This backfills `template:<slug>` source_id values on any NULL rows and writes `.claude/scaffolds/constitution.json` — the scaffold consumers apply during upgrade. Do this BEFORE the DB wipe so the source_id backfill persists.

2. **Dry run reset.** Run `.claude/venv/bin/python .claude/scripts/reset_for_distribution.py --dry-run` and show the user the "Before" table. Rows marked `WIPE` are what will be cleared. Flag any onboarding-row drift the script reports. **Release gate:** if the script reports template articles in status `amended` (edited but not re-affirmed), STOP — these would ship as frozen divergence into every clone. Re-affirm them with `ratify_article` (or revoke) before continuing. The real run exits `4` and refuses unless they are cleared (or `--allow-amended` is passed, which you should only do at the user's explicit request).

3. **Confirm.** Ask the user via `AskUserQuestion` whether to proceed. If there are zero rows to wipe and onboarding is already pristine, tell them the DB is already clean and stop — no need to write.

4. **Apply.** Run `.claude/venv/bin/python .claude/scripts/reset_for_distribution.py` (no flag). Show the "After" diff.

5. **Verify no other leakage.** Run `git diff --stat .claude/claude.db` to confirm only the DB changed, and check `git status` for any unexpected file changes (expect `.claude/scaffolds/constitution.json` to be new/modified from step 1).

6. **Suggest next.** If the cleanup succeeded, point the user at `/release-engine` to draft the version manifest entry. If it failed (exit code != 0), surface the error and stop.

## What gets wiped

- `session_state` — session IDs with absolute paths from the maintainer's machine (a privacy/leak issue).
- `activity_log` — template-dev activity entries.
- `code_routing` — routing entries for files in the maintainer's tree.
- `tasks` — any leftover template-dev tasks.

## What gets reset

- `health_metadata.last_full_audit` → `1970-01-01` (forces a fresh audit on first session after install).
- `review_order` singleton → all counters zeroed.
- `onboarding` row → reset to pristine if any field drifted (asserted after).

## What is preserved

- `constitution` — the ratified articles ARE the template.
- `doc_routing` — the seed routing table for template docs.
- `template_meta` — version history.
- `project_status` — singleton default (`Setup` / `None`).

## Exit codes

- `0` — success.
- `1` — no DB at `.claude/claude.db`.
- `2` — SQL error during reset.
- `3` — onboarding still not pristine after reset (investigate manually).
- `4` — release gate: template articles are `amended` (un-re-affirmed). Re-affirm or revoke them, or pass `--allow-amended` to override.
