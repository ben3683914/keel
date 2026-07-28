#!/usr/bin/env python3
"""Reset the template's claude.db to a pristine state for distribution.

Run before tagging a template release. Wipes per-session working state that
accumulates during template development (leaked file paths, activity rows,
stale routing) while preserving seed data that IS the template (constitution,
doc routing, template_meta).

Usage:
    python reset_for_distribution.py             # apply cleanup
    python reset_for_distribution.py --dry-run   # report only, no writes
    python reset_for_distribution.py --project-root /path/to/repo
"""

import argparse
import subprocess
import sqlite3
import sys
from pathlib import Path


# Tables whose rows are session-/development-scoped and must not ship.
TRUNCATE_TABLES = [
    "session_state",
    "activity_log",
    "code_routing",
    "tasks",
]

# Per-project / singleton state restored explicitly below (see reset_review_order,
# reset_health_audit, reset_projects).
HEALTH_AUDIT_EPOCH = "1970-01-01"


def find_project_root(override: Path | None) -> Path:
    if override:
        return override
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".claude").is_dir():
            return parent
    return cwd


def snapshot_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {}
    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ):
        counts[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    return counts


def onboarding_is_pristine(conn: sqlite3.Connection) -> tuple[bool, list[str]]:
    row = conn.execute("SELECT * FROM onboarding WHERE id = 1").fetchone()
    if row is None:
        return False, ["onboarding row missing"]
    problems = []
    if row["complete"] != 0:
        problems.append(f"complete = {row['complete']} (expected 0)")
    empty_fields = [
        "project_mode", "project_name", "project_purpose", "tech_stack",
        "goals", "branching_strategy", "commit_conventions", "review_strictness",
        "testing_approach", "coding_conventions", "deployment_strategy",
        "team_structure", "greeting", "started_at", "completed_at",
    ]
    for field in empty_fields:
        if row[field]:
            problems.append(f"{field} = {row[field]!r} (expected '')")
    if row["is_existing_repo"] != 0:
        problems.append(f"is_existing_repo = {row['is_existing_repo']} (expected 0)")
    if row["current_phase"] != 0:
        problems.append(f"current_phase = {row['current_phase']} (expected 0)")
    if row["analysis_phases"] not in ("", "[]"):
        problems.append(f"analysis_phases = {row['analysis_phases']!r}")
    if row["phase_progress"] not in ("", "{}"):
        problems.append(f"phase_progress = {row['phase_progress']!r}")
    return (len(problems) == 0, problems)


def amended_template_articles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Template articles edited but not re-affirmed.

    `claude.db` is tracked in git and ships to every clone, so an 'amended'
    template article would land in downstream projects looking like *their* local
    divergence — frozen from future template corrections (engine-update skips
    amended/revoked rows). This is the hard gate that stops that from shipping.
    """
    return conn.execute(
        "SELECT number, title FROM constitution "
        "WHERE status = 'amended' AND source_id LIKE 'template:%' ORDER BY number"
    ).fetchall()


def reset_onboarding(conn: sqlite3.Connection):
    conn.execute("DELETE FROM onboarding")
    conn.execute("INSERT INTO onboarding (id) VALUES (1)")


def reset_health_audit(conn: sqlite3.Connection):
    conn.execute(
        "UPDATE health_metadata SET last_full_audit = ?",
        (HEALTH_AUDIT_EPOCH,),
    )


def reset_review_order(conn: sqlite3.Connection):
    # Per-project review_order: reset every project's pipeline row.
    conn.execute("""
        UPDATE review_order SET
            code_review_done = 0, code_review_critical = 0, code_review_advisory = 0,
            doc_review_done = 0, doc_review_unresolved = 0,
            security_review_done = 0, security_review_issues = 0, security_review_deferred = 0,
            tests_done = 0, tests_failures = 0
    """)


def reset_projects(conn: sqlite3.Connection):
    """Remove any dev-created sub-projects so the shipped registry is just the
    workspace, and point the active-project pointer back at the workspace."""
    sub_ids = [r[0] for r in conn.execute("SELECT id FROM projects WHERE is_workspace = 0")]
    for pid in sub_ids:
        # Clear project-scoped rows that FK to projects without ON DELETE CASCADE.
        conn.execute("DELETE FROM constitution WHERE project_id = ?", (pid,))
        conn.execute("DELETE FROM doc_routing WHERE project_id = ?", (pid,))
        conn.execute("DELETE FROM tasks WHERE project_id = ?", (pid,))
        conn.execute("DELETE FROM activity_log WHERE project_id = ?", (pid,))
        conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
    conn.execute("UPDATE workspace_state SET active_project_id = 1 WHERE id = 1")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument(
        "--allow-amended", action="store_true",
        help="Override the release gate and ship even if template articles are "
             "'amended' (un-re-affirmed). Use only if you know what you're doing.",
    )
    args = parser.parse_args()

    root = find_project_root(args.project_root)
    db_path = root / ".claude" / "claude.db"
    if not db_path.exists():
        print(f"ERROR: no database at {db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Target: {db_path}")
    print(f"Mode:   {'DRY RUN' if args.dry_run else 'APPLY'}")
    print()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    before = snapshot_counts(conn)
    ok, problems = onboarding_is_pristine(conn)
    amended = amended_template_articles(conn)

    print("Before:")
    for name, count in before.items():
        mark = "  WIPE" if name in TRUNCATE_TABLES and count > 0 else "      "
        print(f"  {mark}  {name}: {count}")
    print()

    if not ok:
        print("Onboarding row needs reset:")
        for p in problems:
            print(f"  - {p}")
        print()

    if amended:
        print("RELEASE GATE: template articles edited but not re-affirmed:")
        for row in amended:
            print(f"  - Article {row['number']:03d}: {row['title']} (status 'amended')")
        print("  These will NOT export to the scaffold and would ship as frozen")
        print("  divergence in every clone. Re-affirm with ratify_article (or revoke)")
        print("  before release. Override with --allow-amended only if intentional.")
        print()

    if args.dry_run:
        print("Dry run — no changes written.")
        conn.close()
        return

    if amended and not args.allow_amended:
        print(
            "ABORTED: refusing to reset for distribution while template articles are "
            "'amended'. Re-affirm or revoke them, or pass --allow-amended to override.",
            file=sys.stderr,
        )
        conn.close()
        sys.exit(4)

    try:
        for table in TRUNCATE_TABLES:
            conn.execute(f'DELETE FROM "{table}"')
        if not ok:
            reset_onboarding(conn)
        reset_health_audit(conn)
        reset_review_order(conn)
        reset_projects(conn)
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        conn.close()
        sys.exit(2)

    after = snapshot_counts(conn)
    ok_after, problems_after = onboarding_is_pristine(conn)
    conn.close()

    print("After:")
    for name, count in after.items():
        delta = count - before[name]
        change = f" ({delta:+d})" if delta != 0 else ""
        print(f"        {name}: {count}{change}")
    print()

    if not ok_after:
        print("WARNING: onboarding still not pristine after reset:", file=sys.stderr)
        for p in problems_after:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(3)

    print("Done. DB reset for distribution.")


if __name__ == "__main__":
    main()
