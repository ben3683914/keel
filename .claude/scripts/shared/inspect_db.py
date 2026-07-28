#!/usr/bin/env python3
"""Direct DB inspection for areas without MCP tool coverage.

Usage: python .claude/scripts/shared/inspect_db.py <area>
Areas: doc-routing, code-routing, session, review-order, activity, all
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_db


def fmt_json(text):
    """Format a JSON text field for display."""
    if not text or text in ("[]", "{}"):
        return "--"
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return ", ".join(str(x) for x in parsed) if parsed else "--"
        return str(parsed)
    except (json.JSONDecodeError, TypeError):
        return str(text)[:80]


def inspect_doc_routing(conn):
    rows = conn.execute(
        "SELECT d.path, d.keywords, d.auto_keywords, d.source_paths, d.load_at_start, p.slug "
        "FROM doc_routing d JOIN projects p ON p.id = d.project_id ORDER BY p.id, d.path"
    ).fetchall()
    print(f"=== DOC ROUTING ({len(rows)} entries) ===")
    print(f"{'Project':<12} {'Path':<45} {'Load@Start':<12} {'Keywords'}")
    print("-" * 100)
    for r in rows:
        kw = fmt_json(r["keywords"])
        auto = fmt_json(r["auto_keywords"])
        combined = f"{kw} | auto: {auto}" if auto != "--" else kw
        start = "YES" if r["load_at_start"] else ""
        print(f"{r['slug']:<12} {r['path']:<45} {start:<12} {combined}")


def inspect_code_routing(conn):
    rows = conn.execute(
        "SELECT c.path, c.description, c.line_count, c.exports, c.dependencies, c.load_at_start, p.slug "
        "FROM code_routing c JOIN projects p ON p.id = c.project_id ORDER BY p.id, c.path"
    ).fetchall()
    print(f"=== CODE ROUTING ({len(rows)} entries) ===")
    print(f"{'Project':<12} {'Path':<45} {'Lines':<8} {'Load@Start':<12} {'Description'}")
    print("-" * 110)
    for r in rows:
        start = "YES" if r["load_at_start"] else ""
        desc = (r["description"] or "")[:40]
        print(f"{r['slug']:<12} {r['path']:<45} {r['line_count']:<8} {start:<12} {desc}")


def inspect_session(conn):
    rows = conn.execute(
        "SELECT session_id, modified_files, mcp_tools, "
        "docs_unresolved_issues, tests_failures, security_issues, "
        "code_critical_issues, created_at, updated_at "
        "FROM session_state ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    print(f"=== SESSION STATE ({len(rows)} recent sessions) ===")
    for r in rows:
        print(f"\nSession: {r['session_id'][:20]}...")
        print(f"  Created: {r['created_at']}  Updated: {r['updated_at']}")
        mods = fmt_json(r["modified_files"])
        tools = fmt_json(r["mcp_tools"])
        print(f"  Modified files: {mods}")
        print(f"  MCP tools called: {tools}")
        print(f"  Issues — docs: {r['docs_unresolved_issues']}, "
              f"tests: {r['tests_failures']}, "
              f"security: {r['security_issues']}, "
              f"code critical: {r['code_critical_issues']}")


def inspect_review_order(conn):
    print("=== REVIEW ORDER (per project) ===")
    rows = conn.execute(
        "SELECT r.*, p.slug FROM review_order r JOIN projects p ON p.id = r.project_id "
        "ORDER BY p.id"
    ).fetchall()
    if not rows:
        print("(no review state)")
        return
    for row in rows:
        print(f"[{row['slug']}]")
        print(f"  Code review:    done={bool(row['code_review_done'])}  "
              f"critical={row['code_review_critical']}  advisory={row['code_review_advisory']}")
        print(f"  Doc review:     done={bool(row['doc_review_done'])}  "
              f"unresolved={row['doc_review_unresolved']}")
        print(f"  Security review: done={bool(row['security_review_done'])}  "
              f"issues={row['security_review_issues']}  deferred={row['security_review_deferred']}")
        print(f"  Tests:          done={bool(row['tests_done'])}  "
              f"failures={row['tests_failures']}")


def inspect_activity(conn):
    rows = conn.execute(
        "SELECT date, message FROM activity_log ORDER BY id DESC LIMIT 20"
    ).fetchall()
    print(f"=== ACTIVITY LOG ({len(rows)} entries) ===")
    if not rows:
        print("(empty)")
        return
    for r in rows:
        print(f"  {r['date']}  {r['message']}")


AREAS = {
    "doc-routing": inspect_doc_routing,
    "code-routing": inspect_code_routing,
    "session": inspect_session,
    "review-order": inspect_review_order,
    "activity": inspect_activity,
}


def main():
    area = sys.argv[1] if len(sys.argv) > 1 else "all"

    if area not in AREAS and area != "all":
        print(f"Unknown area: {area}")
        print(f"Available: {', '.join(AREAS.keys())}, all")
        sys.exit(1)

    conn = get_db()
    try:
        if area == "all":
            for name, fn in AREAS.items():
                fn(conn)
                print()
        else:
            AREAS[area](conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
