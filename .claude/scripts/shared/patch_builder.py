#!/usr/bin/env python3
"""Patch builder helper for the /create-patch skill.

Scans git changes, classifies files by layer, checks manifests,
and writes version entries into engine-update.py.

Usage:
    python patch_builder.py --scan                    # Scan and classify changes
    python patch_builder.py --check                   # Validate current manifest
    python patch_builder.py --write --version X.Y.Z --data '{...}'  # Write entry
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_db, json_loads

# File classification rules: pattern -> (layer, action)
# When several patterns match a path, the MOST SPECIFIC one wins (see
# classify_file) — exact paths beat globs, longer literal prefixes beat shorter
# ones — so list order does not matter and specific rules are never shadowed.
CLASSIFICATION_RULES = [
    # Engine: scripts
    (".claude/scripts/hooks/*", "engine", "overwrite"),
    (".claude/scripts/mcp/*", "engine", "overwrite"),
    (".claude/scripts/shared/*", "engine", "overwrite"),
    (".claude/scripts/engine-update.py", "engine", "overwrite"),
    # Top-level maintainer scripts (e.g. reset_for_distribution.py). More specific
    # rules above win for subdirs; the engine-update.py exact rule wins for itself.
    (".claude/scripts/*", "engine", "overwrite"),
    # Engine: agents, skills, config
    (".claude/agents/*", "engine", "overwrite"),
    (".claude/skills/*", "engine", "add"),
    (".claude/skills/*/SKILL.md", "engine", "overwrite"),
    (".claude/skills/*/*.md", "engine", "overwrite"),
    (".mcp.json", "engine", "overwrite"),
    ("setup.sh", "engine", "overwrite"),
    ("start-workspace.bat", "engine", "overwrite"),
    (".gitattributes", "engine", "overwrite"),
    # Engine: scaffolds (consumed by assemble.py to generate CLAUDE.md + settings.json)
    (".claude/scaffolds/*", "engine", "add"),
    (".claude/scaffolds/settings/*", "engine", "add"),
    (".claude/scaffolds/constitution.json", "constitution", "apply_constitution_scaffold"),
    # Engine docs
    ("docs/claude/*", "engine_docs", "overwrite"),
    # Hybrid
    (".claude/settings.json", "hybrid", "merge_json"),
    (".claude/doc-enforcement.json", "hybrid", "merge_json"),
    ("CLAUDE.md", "hybrid", "merge_section"),
    (".gitignore", "hybrid", "merge_append"),
    ("docs/guides/*", "hybrid", "merge_section"),
    (".vscode/*", "hybrid", "merge_json"),
    # Project (never patch)
    ("docs/constitution/*", "project", None),
    ("docs/core/*", "project", None),
    ("docs/features/*", "project", None),
    ("README.md", "project", None),
    (".claude/project-config.json", "project", None),
    (".claude/claude.db", "project", None),
    (".claude/settings.local.json", "project", None),
    ("project/*", "project", None),
    ("docs/index.md", "project", None),
]


# merge_json files need a named strategy (engine-update's action_merge_json reads
# change["strategy"]). merge_section files need a curated change["section"] — which
# template-owned section changed — and that can't be inferred mechanically.
MERGE_JSON_STRATEGY = {
    ".claude/settings.json": "deep_merge_hooks",
    ".claude/doc-enforcement.json": "deep_merge_rules",
}


def merge_json_strategy(filepath):
    fp = filepath.replace("\\", "/")
    if fp in MERGE_JSON_STRATEGY:
        return MERGE_JSON_STRATEGY[fp]
    if fp.startswith(".vscode/"):
        return "add_missing"
    return ""


def match_pattern(filepath, pattern):
    """Simple glob-style matching for classification."""
    filepath = filepath.replace("\\", "/")
    pattern = pattern.replace("\\", "/")

    if "*" not in pattern:
        return filepath == pattern

    # Handle dir/* patterns
    if pattern.endswith("/*"):
        prefix = pattern[:-2]
        # Match files directly in the dir (not deeper)
        if "/" in filepath:
            parent = filepath.rsplit("/", 1)[0]
            return parent == prefix or filepath.startswith(prefix + "/")
        return False

    # Handle dir/*/file patterns
    if "/*/" in pattern:
        prefix, suffix = pattern.split("/*/", 1)
        if not filepath.startswith(prefix + "/"):
            return False
        rest = filepath[len(prefix) + 1:]
        parts = rest.split("/", 1)
        if len(parts) == 2:
            return parts[1] == suffix
        return False

    return False


def classify_file(filepath):
    """Classify a file path into a layer and action.

    When multiple patterns match, the most specific wins: an exact (wildcard-free)
    pattern outranks any glob, and among globs the one with more literal
    characters wins. This keeps specific rules like `.claude/skills/*/SKILL.md`
    from being shadowed by broader ones like `.claude/skills/*`, regardless of
    their order in CLASSIFICATION_RULES.
    """
    best = None
    best_score = -1
    for pattern, layer, action in CLASSIFICATION_RULES:
        if match_pattern(filepath, pattern):
            score = len(pattern.replace("*", "")) + (1000 if "*" not in pattern else 0)
            if score > best_score:
                best_score = score
                best = (layer, action)
    return best if best is not None else ("unknown", None)


def run_git(*args):
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_tracked_files():
    """Get set of files tracked by git."""
    code, out, _ = run_git("ls-files")
    return set(out.splitlines()) if out else set()


def get_last_release_tag():
    """Most recent vX.Y.Z release tag reachable from HEAD, or None.

    Releases are tagged `v<major>.<minor>.<patch>`. We baseline the scan on the
    last such tag so that changes already committed since the release (but not
    yet shipped in a manifest entry) are still detected — `git diff HEAD` alone
    would miss them.
    """
    code, out, _ = run_git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*")
    return out if code == 0 and out else None


def files_at_ref(ref):
    """Set of tracked file paths as of the given ref (commit/tag)."""
    code, out, _ = run_git("ls-tree", "-r", "--name-only", ref)
    return set(out.splitlines()) if code == 0 and out else set()


def get_changed_files(since_tag=None):
    """Files changed since the last release, including working-tree edits.

    Union of:
      - committed changes since `since_tag` (`git diff <tag> HEAD`), if a tag
        was found — this is what catches committed-but-unreleased work; and
      - current working-tree changes vs HEAD (staged, unstaged, untracked).
    """
    files = set()

    if since_tag:
        code, out, _ = run_git("diff", "--name-only", since_tag, "HEAD")
        if out:
            files.update(out.splitlines())

    # Working-tree changes vs HEAD (covers staged + unstaged).
    code, out, _ = run_git("diff", "--name-only", "HEAD")
    if out:
        files.update(out.splitlines())

    # Untracked files. git collapses a fully-untracked directory to a single
    # `?? dir/` entry, so expand any such directory to its individual files —
    # the patch system copies files, not directories.
    _, toplevel, _ = run_git("rev-parse", "--show-toplevel")
    root = Path(toplevel) if toplevel else Path.cwd()
    code, out, _ = run_git("status", "--porcelain")
    for line in out.splitlines():
        if line.startswith("?? "):
            p = line[3:].strip().rstrip("/")
            full = root / p
            if full.is_dir():
                for f in full.rglob("*"):
                    if f.is_file():
                        files.add(str(f.relative_to(root)).replace("\\", "/"))
            else:
                files.add(p)

    return sorted(f for f in files if f)


def check_db_schema_change(changed_files):
    """Check if db.py was modified (potential migration needed)."""
    return any("shared/db.py" in f for f in changed_files)


def scan(args):
    """Scan git changes and classify files."""
    since_tag = get_last_release_tag()
    changed = get_changed_files(since_tag)
    if not changed:
        print(json.dumps({
            "message": "No changes detected",
            "baseline": since_tag or "HEAD (no release tag found)",
            "files": {},
        }, indent=2))
        return

    classified = {"engine": [], "engine_docs": [], "hybrid": [], "constitution": [], "project": [], "unknown": []}
    warnings = []

    for filepath in changed:
        layer, action = classify_file(filepath)
        entry = {"path": filepath, "action": action}
        if action == "merge_json":
            strat = merge_json_strategy(filepath)
            if strat:
                entry["strategy"] = strat
            else:
                warnings.append(f"{filepath}: merge_json needs a 'strategy' — set it manually.")
        elif action == "merge_section":
            entry["section"] = "TODO-SPECIFY-SECTION"
            warnings.append(
                f"{filepath}: merge_section needs curated 'section' entries — one per "
                "changed, TEMPLATE-OWNED section. Exclude consumer-owned sections "
                "(e.g. '## Quick Reference', the project title block). Replace the TODO."
            )
        classified[layer].append(entry)

    # Get current version
    conn = get_db()
    try:
        row = conn.execute("SELECT template_version FROM template_meta WHERE id = 1").fetchone()
        current_version = row["template_version"] if row else "1.0.0"
    finally:
        conn.close()

    # Auto-determine version bump level
    schema_changed = check_db_schema_change(changed)
    has_engine = len(classified["engine"]) > 0
    has_engine_docs = len(classified["engine_docs"]) > 0
    has_hybrid = len(classified["hybrid"]) > 0
    # "New" means the file did not exist at the last release. With a tag baseline
    # that includes files committed since the release; without one, fall back to
    # untracked working-tree files.
    baseline_files = files_at_ref(since_tag) if since_tag else get_tracked_files()
    has_new_files = any(
        f["path"] not in baseline_files for cat in classified.values() for f in cat
    )

    parts = [int(x) for x in current_version.split(".")]
    # Major: DB schema breaking changes, hybrid merge strategy changes, or removal of engine files
    # Minor: New engine files, new skills, new features, schema additions (new tables/columns)
    # Patch: Bug fixes, doc updates, tweaks to existing engine files
    if schema_changed or has_hybrid:
        bump = "minor"
        suggested = f"{parts[0]}.{parts[1] + 1}.0"
        bump_reason = []
        if schema_changed:
            bump_reason.append("DB schema changed")
        if has_hybrid:
            bump_reason.append("hybrid files modified (merge required)")
    elif has_new_files or has_engine:
        # Check if it's just fixes to existing files or new functionality
        if has_new_files:
            bump = "minor"
            suggested = f"{parts[0]}.{parts[1] + 1}.0"
            bump_reason = ["new files added"]
        else:
            bump = "patch"
            suggested = f"{parts[0]}.{parts[1]}.{parts[2] + 1}"
            bump_reason = ["existing engine files modified"]
    elif has_engine_docs:
        bump = "patch"
        suggested = f"{parts[0]}.{parts[1]}.{parts[2] + 1}"
        bump_reason = ["engine docs updated"]
    else:
        bump = "patch"
        suggested = f"{parts[0]}.{parts[1]}.{parts[2] + 1}"
        bump_reason = ["minor changes"]

    output = {
        "current_version": current_version,
        "baseline": since_tag or "HEAD (no release tag found)",
        "suggested_version": suggested,
        "bump_level": bump,
        "bump_reason": bump_reason,
        "schema_changed": schema_changed,
        "warnings": warnings,
        "files": {
            "engine": classified["engine"],
            "engine_docs": classified["engine_docs"],
            "hybrid": classified["hybrid"],
            "constitution": classified["constitution"],
            "project": classified["project"],
            "unknown": classified["unknown"],
        },
        "counts": {
            "engine": len(classified["engine"]),
            "engine_docs": len(classified["engine_docs"]),
            "hybrid": len(classified["hybrid"]),
            "constitution": len(classified["constitution"]),
            "project": len(classified["project"]),
            "unknown": len(classified["unknown"]),
        },
    }

    print(json.dumps(output, indent=2))


def check(args):
    """Validate current manifest in engine-update.py."""
    engine_path = Path(__file__).resolve().parent.parent / "engine-update.py"
    if not engine_path.exists():
        print(json.dumps({"error": "engine-update.py not found"}, indent=2))
        sys.exit(1)

    content = engine_path.read_text(encoding="utf-8")

    # Extract VERSIONS and MIGRATIONS by running just those assignments
    try:
        # Find and eval just the constants, not the whole script
        versions = []
        migrations = {}

        # Extract VERSIONS list
        v_match = re.search(r"^VERSIONS\s*=\s*\[", content, re.MULTILINE)
        if v_match:
            bracket_depth = 0
            start = v_match.start()
            end = None
            for i in range(v_match.end(), len(content)):
                if content[i] == "[":
                    bracket_depth += 1
                elif content[i] == "]":
                    if bracket_depth == 0:
                        end = i + 1
                        break
                    bracket_depth -= 1
            if end:
                versions = eval(content[v_match.start() + len("VERSIONS = "):end])

        # Extract MIGRATIONS dict
        m_match = re.search(r"^MIGRATIONS\s*=\s*\{", content, re.MULTILINE)
        if m_match:
            brace_depth = 0
            start = m_match.start()
            end = None
            for i in range(m_match.end(), len(content)):
                if content[i] == "{":
                    brace_depth += 1
                elif content[i] == "}":
                    if brace_depth == 0:
                        end = i + 1
                        break
                    brace_depth -= 1
            if end:
                migrations = eval(content[m_match.start() + len("MIGRATIONS = "):end])

    except Exception as e:
        print(json.dumps({"error": f"Failed to parse engine-update.py: {e}"}, indent=2))
        sys.exit(1)

    issues = []

    # Check for duplicate versions
    seen_versions = set()
    for v in versions:
        ver = v.get("version", "")
        if ver in seen_versions:
            issues.append(f"Duplicate version: {ver}")
        seen_versions.add(ver)

    # Check migration references
    for v in versions:
        for mig_key in v.get("migrations", []):
            if mig_key not in migrations:
                issues.append(f"Version {v['version']} references missing migration: {mig_key}")

    # Check that referenced files exist
    for v in versions:
        for cat, changes in v.get("changes", {}).items():
            for change in changes:
                path = change.get("path", "")
                if change.get("action") != "delete" and not Path(path).exists():
                    issues.append(f"Version {v['version']}: file not found: {path}")

    # Get current DB version
    conn = get_db()
    try:
        row = conn.execute("SELECT template_version FROM template_meta WHERE id = 1").fetchone()
        db_version = row["template_version"] if row else "1.0.0"
    finally:
        conn.close()

    manifest_latest = versions[-1]["version"] if versions else db_version

    output = {
        "db_version": db_version,
        "manifest_versions": [v["version"] for v in versions],
        "manifest_latest": manifest_latest,
        "migration_keys": list(migrations.keys()),
        "issues": issues,
        "valid": len(issues) == 0,
    }

    print(json.dumps(output, indent=2))


def write(args):
    """Write a new version entry into engine-update.py."""
    if not args.version or not args.data:
        print(json.dumps({"error": "Both --version and --data are required"}, indent=2))
        sys.exit(1)

    try:
        entry_data = json.loads(args.data)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON data: {e}"}, indent=2))
        sys.exit(1)

    engine_path = Path(__file__).resolve().parent.parent / "engine-update.py"
    if not engine_path.exists():
        print(json.dumps({"error": "engine-update.py not found"}, indent=2))
        sys.exit(1)

    content = engine_path.read_text(encoding="utf-8")

    # Build the version entry as Python code
    version_entry = {
        "version": args.version,
        "description": entry_data.get("description", ""),
        "migrations": entry_data.get("migrations", []),
        "changes": entry_data.get("changes", {}),
    }

    # Format as Python dict with proper indentation
    entry_lines = ["    {"]
    entry_lines.append(f'        "version": {json.dumps(version_entry["version"])},')
    entry_lines.append(f'        "description": {json.dumps(version_entry["description"])},')
    entry_lines.append(f'        "migrations": {json.dumps(version_entry["migrations"])},')
    entry_lines.append('        "changes": {')

    for cat, changes in version_entry["changes"].items():
        entry_lines.append(f'            "{cat}": [')
        for change in changes:
            entry_lines.append(f"                {json.dumps(change)},")
        entry_lines.append("            ],")

    entry_lines.append("        },")
    entry_lines.append("    },")
    entry_str = "\n".join(entry_lines)

    # Also write migrations if provided
    new_migrations = entry_data.get("new_migrations", {})
    if new_migrations:
        for key, sql in new_migrations.items():
            mig_entry = f'    "{key}": """{sql}""",\n'
            # Insert before closing brace of MIGRATIONS
            mig_pattern = r"(MIGRATIONS\s*=\s*\{[^}]*)"
            match = re.search(mig_pattern, content, re.DOTALL)
            if match:
                insert_pos = match.end()
                content = content[:insert_pos] + "\n" + mig_entry + content[insert_pos:]

    # Insert the version entry before the closing bracket of VERSIONS
    # Find VERSIONS = [ ... ] and insert before the last ]
    versions_pattern = r"(VERSIONS\s*=\s*\[)"
    match = re.search(versions_pattern, content)
    if not match:
        print(json.dumps({"error": "Could not find VERSIONS list in engine-update.py"}, indent=2))
        sys.exit(1)

    # Find the closing ] of VERSIONS
    bracket_depth = 0
    start = match.start()
    insert_pos = None
    for i in range(match.end(), len(content)):
        if content[i] == "[":
            bracket_depth += 1
        elif content[i] == "]":
            if bracket_depth == 0:
                insert_pos = i
                break
            bracket_depth -= 1

    if insert_pos is None:
        print(json.dumps({"error": "Could not find end of VERSIONS list"}, indent=2))
        sys.exit(1)

    # Insert entry before the closing ]
    content = content[:insert_pos] + "\n" + entry_str + "\n" + content[insert_pos:]

    engine_path.write_text(content, encoding="utf-8", newline="\n")

    # Update the template's own DB version to match the new manifest entry
    from datetime import date
    conn = get_db()
    try:
        row = conn.execute("SELECT update_history FROM template_meta WHERE id = 1").fetchone()
        history = json_loads(row["update_history"]) if row else []
        history.append({
            "version": args.version,
            "date": date.today().isoformat(),
            "action": "release",
        })
        today = date.today().isoformat()
        conn.execute(
            "UPDATE template_meta SET template_version = ?, last_updated = ?, update_history = ? WHERE id = 1",
            (args.version, today, json.dumps(history)),
        )
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({
        "success": True,
        "version": args.version,
        "files_in_manifest": sum(
            len(changes) for changes in version_entry["changes"].values()
        ),
        "migrations_added": list(new_migrations.keys()),
    }, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Patch builder for template engine updates")
    parser.add_argument("--scan", action="store_true", help="Scan and classify changed files")
    parser.add_argument("--check", action="store_true", help="Validate current manifest")
    parser.add_argument("--write", action="store_true", help="Write version entry to manifest")
    parser.add_argument("--version", help="Version number for --write")
    parser.add_argument("--data", help="JSON data for --write")

    args = parser.parse_args()

    if args.scan:
        scan(args)
    elif args.check:
        check(args)
    elif args.write:
        write(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
