"""new_project validation: the shared project-creation helper.

Confirms the single code path that onboarding (single/scratch/multi) and
/add-project all use: it scaffolds ./<slug>/, appends a well-formed projects[]
entry, rejects duplicates and the repo root, never clobbers existing files, and
(with refresh) routes the new folder's source to the NEW project row — not the
workspace. This is the behavior that keeps a single project off the root.

    .claude/venv/bin/python .claude/scripts/tests/test_new_project.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS / "shared"))
sys.path.insert(0, str(SCRIPTS))

_checks = 0
_failures = []


def check(label, cond):
    global _checks
    _checks += 1
    print(f"  {'ok:  ' if cond else 'FAIL:'} {label}")
    if not cond:
        _failures.append(label)


def load_projects(root: Path):
    cfg = json.loads((root / ".claude" / "project-config.json").read_text())
    return cfg.get("projects", [])


def run(root: Path):
    import new_project as NP
    from db import get_db
    import projects as P

    get_db()  # bootstrap schema + workspace row

    # 1. Create a project (new folder, no refresh needed for scaffold checks).
    entry = NP.add_project(
        slug="My App", name="My App", description="A test app",
        source_roots=["src"], source_extensions=[".py"],
        test_command="pytest", refresh=False,
    )
    check("slug is slugified", entry["slug"] == "my-app")
    check("path defaults to slug", entry["path"] == "my-app")
    check("folder created", (root / "my-app").is_dir())
    check("docs/index.md scaffolded", (root / "my-app" / "docs" / "index.md").exists())
    check("README stub scaffolded", (root / "my-app" / "README.md").exists())
    check("index.md carries version metadata",
          "**Version:**" in (root / "my-app" / "docs" / "index.md").read_text())
    projs = load_projects(root)
    check("one projects[] entry written", len(projs) == 1)
    check("entry carries its own source config",
          projs[0].get("source_roots") == ["src"] and projs[0].get("source_extensions") == [".py"])

    # With exactly one real project, the active pointer defaults to it (never the
    # empty workspace umbrella) even though bootstrap seeds the pointer to workspace.
    # (sync_projects_from_config runs at every MCP/hook entry in real usage.)
    conn = get_db()
    try:
        P.sync_projects_from_config(conn, {"projects": load_projects(root)})
        mid = P.get_project_by_slug(conn, "my-app")["id"]
        check("single project is the active default", P.get_active_project_id(conn) == mid)
        check("explicit project=workspace still resolves to workspace",
              P.resolve_project(conn, {"project": "workspace"})[1] == "workspace")
    finally:
        conn.close()

    # 2. Duplicate slug and duplicate path are rejected.
    try:
        NP.add_project(slug="my-app", name="Dup", refresh=False)
        check("duplicate slug rejected", False)
    except ValueError:
        check("duplicate slug rejected", True)
    try:
        NP.add_project(slug="other", name="Other", path="my-app", refresh=False)
        check("duplicate path rejected", False)
    except ValueError:
        check("duplicate path rejected", True)

    # 3. The repo root is never a valid project path. (An empty --path is NOT an
    #    error — it means "use the slug default", which is always a real subfolder.)
    for bad in (".", "./", ".."):
        try:
            NP.add_project(slug=f"root-{len(bad)}", name="Root", path=bad, refresh=False)
            check(f"root path {bad!r} rejected", False)
        except ValueError:
            check(f"root path {bad!r} rejected", True)

    # 4. Non-destructive: a populated folder's README/docs are left untouched.
    (root / "existing" / "docs").mkdir(parents=True)
    (root / "existing" / "README.md").write_text("KEEP ME", encoding="utf-8")
    (root / "existing" / "docs" / "index.md").write_text("KEEP DOCS", encoding="utf-8")
    NP.add_project(slug="existing", name="Existing", path="existing", refresh=False)
    check("existing README not clobbered",
          (root / "existing" / "README.md").read_text() == "KEEP ME")
    check("existing docs/index.md not clobbered",
          (root / "existing" / "docs" / "index.md").read_text() == "KEEP DOCS")

    # 5. With refresh, the project's source routes to the NEW row, not workspace.
    (root / "routed" / "src").mkdir(parents=True)
    (root / "routed" / "src" / "app.py").write_text("def go():\n    pass\n", encoding="utf-8")
    NP.add_project(slug="routed", name="Routed", path="routed",
                   source_roots=["src"], source_extensions=[".py"], refresh=True)
    conn = get_db()
    try:
        rid = P.get_project_by_slug(conn, "routed")["id"]
        code = {(r["path"], r["project_id"]) for r in
                conn.execute("SELECT path, project_id FROM code_routing")}
        check("new project's source routed to its own row",
              ("routed/src/app.py", rid) in code)
        check("workspace did NOT claim the project's source",
              ("routed/src/app.py", 1) not in code)
    finally:
        conn.close()


def main():
    prev = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".claude").mkdir(parents=True)
        (root / ".claude" / "project-config.json").write_text(
            json.dumps({"enforcement": "full", "projects": []}), encoding="utf-8"
        )
        os.chdir(root)
        try:
            run(root)
        finally:
            os.chdir(prev)
    print()
    if _failures:
        print(f"NEW-PROJECT: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"NEW-PROJECT: all {_checks} checks passed")


if __name__ == "__main__":
    main()
