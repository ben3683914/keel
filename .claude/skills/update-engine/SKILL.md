---
name: update-engine
description: Check for and apply template engine updates
disable-model-invocation: true
argument-hint: "[source-path]"
---

Interactive template update skill. Runs `.claude/scripts/engine-update.py` and presents results to the user.

If `$ARGUMENTS` contains a path, use it as the source. Otherwise ask for it when needed.

## Menu

Present this menu via AskUserQuestion:

1. **Check status** — show current template version and update history
2. **Check for updates** — preview available changes (dry run)
3. **Apply updates** — select categories and apply

## Option 1: Status

```
.claude/venv/bin/python .claude/scripts/engine-update.py --status
```

Parse JSON output. Show: current version, last updated date, update history entries.

## Option 2: Check for Updates

Ask for source template path if not provided via `$ARGUMENTS`.

```
.claude/venv/bin/python .claude/scripts/engine-update.py --dry-run --source "<path>"
```

Parse JSON output. For each available version, present:

### Version Impact Summary

For each version in the update path, show:
- **Version number** and description
- **Bump level** (major/minor/patch) with explanation:
  - Major: Breaking changes — may require manual intervention
  - Minor: New features, schema additions, hybrid merges needed — review recommended
  - Patch: Bug fixes and tweaks — safe to apply
- **Categories affected** with file counts
- **Migrations**: any DB schema changes (highlight these — they change project state)
- **Hybrid files**: list which files will need merge (these need user review)

Example presentation:
```
Available updates: 1.0.0 → 1.2.0 (2 versions)

v1.1.0 (MINOR) — New push skill and patch system
  Engine:      8 files (overwrite)
  Engine docs: 0 files
  Hybrid:      3 files (merge required — settings.json, CLAUDE.md, setup.md)
  Migrations:  1 (template_meta table)

v1.2.0 (PATCH) — Fix commit gate edge case
  Engine:      1 file (overwrite)
  Engine docs: 1 file
  Hybrid:      0 files
  Migrations:  0
```

Ask if user wants to proceed to apply, and if so which versions (all, or up to a specific version).

## Option 3: Apply Updates

If dry-run wasn't done yet, run it first to show the impact summary above. Then:

1. Present categories with file counts (e.g., `engine (12 files)`, `engine_docs (4 files)`, `hybrid (3 files)`)
2. Ask user which categories to apply via AskUserQuestion (or "all")
3. For hybrid category: note that merge diffs will be shown for review
4. Run: `.claude/venv/bin/python .claude/scripts/engine-update.py --source "<path>" --categories <selected> --yes`
5. Parse JSON output. Report: files updated, migrations run, new version number
6. If hybrid files had conflicts, present them for manual resolution
