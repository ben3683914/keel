"""Export the template's constitution to a diffable scaffold.

Run from inside the template repo (where `template_dev: true`). This script:

1. Backfills `template:<slug>` source_id values for any rows that still have
   NULL (e.g. pre-existing articles written before the source_id column was
   added).
2. Dumps all ratified articles to `.claude/scaffolds/constitution.json` in a
   stable, human-reviewable shape.

Consumers (projects created from the template) never run this script — they
consume the scaffold via `action_apply_constitution_scaffold` during
`engine-update`.

Usage:
    python .claude/scripts/shared/constitution_export.py
    python .claude/scripts/shared/constitution_export.py --dry-run
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_db
from slugify import slugify


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCAFFOLD_PATH = PROJECT_ROOT / ".claude" / "scaffolds" / "constitution.json"


def backfill_source_ids(conn: sqlite3.Connection) -> list[dict]:
    """Assign `template:<slug>` to any row with NULL source_id.

    Slug collisions are resolved by appending -2, -3, ... Returns a list of
    assignments for reporting.
    """
    rows = conn.execute(
        "SELECT number, title FROM constitution WHERE source_id IS NULL ORDER BY number"
    ).fetchall()

    used = {
        r["source_id"]
        for r in conn.execute(
            "SELECT source_id FROM constitution WHERE source_id IS NOT NULL"
        ).fetchall()
    }

    assignments: list[dict] = []
    for row in rows:
        base_slug = slugify(row["title"])
        slug = base_slug
        suffix = 2
        while f"template:{slug}" in used:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        source_id = f"template:{slug}"
        conn.execute(
            "UPDATE constitution SET source_id = ? WHERE number = ?",
            (source_id, row["number"]),
        )
        used.add(source_id)
        assignments.append({
            "number": row["number"],
            "title": row["title"],
            "source_id": source_id,
        })
    return assignments


def amended_template_articles(conn: sqlite3.Connection) -> list[dict]:
    """Template articles edited but not re-affirmed.

    These are excluded from the export (export_scaffold only selects 'ratified'),
    so surface them as a warning: the author almost certainly meant to re-affirm.
    """
    rows = conn.execute(
        "SELECT number, title FROM constitution "
        "WHERE status = 'amended' AND source_id LIKE 'template:%' ORDER BY number"
    ).fetchall()
    return [{"number": r["number"], "title": r["title"]} for r in rows]


def load_template_config() -> dict:
    cfg = PROJECT_ROOT / ".claude" / "project-config.json"
    if not cfg.exists():
        return {}
    try:
        return json.loads(cfg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def get_template_version() -> str:
    return load_template_config().get("template_version", "0.0.0")


def export_scaffold(conn: sqlite3.Connection) -> dict:
    """Build the JSON shape written to scaffolds/constitution.json."""
    rows = conn.execute(
        "SELECT source_id, number, title, status, category, context, "
        "rule_text, consequences, enforcement, created_date, ratified_date "
        "FROM constitution WHERE status = 'ratified' "
        "AND source_id LIKE 'template:%' ORDER BY number"
    ).fetchall()

    articles = []
    for r in rows:
        articles.append({
            "source_id": r["source_id"],
            "number": r["number"],
            "title": r["title"],
            "category": r["category"] or "general",
            "context": r["context"] or "",
            "rule_text": r["rule_text"],
            "consequences": r["consequences"] or "",
            "enforcement": r["enforcement"] or "",
            "created_date": r["created_date"],
            "ratified_date": r["ratified_date"] or "",
        })

    return {
        "schema_version": 1,
        "template_version": get_template_version(),
        "articles": articles,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report without writing DB or scaffold.")
    args = parser.parse_args()

    conn = get_db(PROJECT_ROOT)
    try:
        unfinalized = amended_template_articles(conn)

        if args.dry_run:
            null_rows = conn.execute(
                "SELECT COUNT(*) FROM constitution WHERE source_id IS NULL"
            ).fetchone()[0]
            ratified = conn.execute(
                "SELECT COUNT(*) FROM constitution WHERE status = 'ratified'"
            ).fetchone()[0]
            print(json.dumps({
                "dry_run": True,
                "articles_ratified": ratified,
                "rows_missing_source_id": null_rows,
                "amended_not_reaffirmed": unfinalized,
                "scaffold_path": str(SCAFFOLD_PATH),
            }, indent=2))
            if unfinalized:
                print(
                    f"\nWARNING: {len(unfinalized)} template article(s) are 'amended' but not "
                    "re-affirmed; they will NOT be exported. Re-affirm with ratify_article "
                    "or revoke before release.",
                    file=sys.stderr,
                )
            return

        assignments = backfill_source_ids(conn)
        conn.commit()
        scaffold = export_scaffold(conn)
    finally:
        conn.close()

    if unfinalized:
        print(
            f"\nWARNING: {len(unfinalized)} template article(s) are 'amended' but not "
            "re-affirmed and were EXCLUDED from the scaffold: "
            + ", ".join(f"{a['number']:03d} {a['title']}" for a in unfinalized)
            + ". Re-affirm with ratify_article or revoke before release.",
            file=sys.stderr,
        )

    SCAFFOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCAFFOLD_PATH.write_text(
        json.dumps(scaffold, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    print(json.dumps({
        "scaffold_path": str(SCAFFOLD_PATH),
        "template_version": scaffold["template_version"],
        "articles_exported": len(scaffold["articles"]),
        "source_id_backfilled": assignments,
    }, indent=2))


if __name__ == "__main__":
    main()
