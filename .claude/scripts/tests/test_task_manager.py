"""task_manager validation: project-scoped task_manager handlers.

Self-running (no pytest dependency). Exercises the real task_manager MCP
handlers against an isolated temp db. Because the handlers call bare get_db()
(which resolves Path.cwd()), the test chdir's into the temp workspace -- the
same isolation pattern phase-1 uses -- so the tracked .claude/claude.db is
never touched.

    .claude/venv/bin/python .claude/scripts/tests/test_task_manager.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

SHARED = Path(__file__).resolve().parent.parent / "shared"
MCP = Path(__file__).resolve().parent.parent / "mcp"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(MCP))

_checks = 0
_failures = []


def check(label, cond):
    global _checks
    _checks += 1
    print(f"  {'ok:  ' if cond else 'FAIL:'} {label}")
    if not cond:
        _failures.append(label)


def text(result):
    """Flatten an MCP handler result (list[TextContent]) to a single string."""
    return "\n".join(tc.text for tc in result)


def _set_active(P, get_db, pid):
    c = get_db()
    try:
        P.set_active_project(c, pid)
    finally:
        c.close()


def _active(P, get_db):
    c = get_db()
    try:
        return P.get_active_project_id(c)
    finally:
        c.close()


def run(root: Path):
    import projects as P
    from db import get_db
    import task_manager as T

    # --- seed a second real project; workspace(1) is always present ---
    c = get_db()
    try:
        web_id = P.ensure_project(c, "web", "Web", "apps/web")
        api_id = P.ensure_project(c, "api", "API", "services/api")
    finally:
        c.close()
    check("seeded two distinct projects", web_id != api_id and web_id > 1)

    # --- create_task stamps the ACTIVE project (cross-connection pointer read) ---
    _set_active(P, get_db, web_id)
    res = T.handle_create_task({"title": "Login form", "description": "Build the login form"})
    check("create_task echoes active project (web)", text(res).startswith("[project: web]\n"))
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT task_id, project_id FROM tasks WHERE title = 'Login form'"
        ).fetchone()
        web_task = row["task_id"]
        check("create_task stamped project_id = active (web)", row["project_id"] == web_id)
    finally:
        conn.close()

    # --- explicit project= files under that project WITHOUT moving the pointer ---
    res = T.handle_create_task(
        {"title": "API rate limit", "description": "Add a rate limiter", "project": "api"}
    )
    check("create_task explicit project echoes api", text(res).startswith("[project: api]\n"))
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT task_id, project_id FROM tasks WHERE title = 'API rate limit'"
        ).fetchone()
        api_task = row["task_id"]
        check("create_task explicit stamped project_id = api", row["project_id"] == api_id)
    finally:
        conn.close()
    check(
        "explicit project= did NOT move the active pointer (still web)",
        _active(P, get_db) == web_id,
    )

    # --- task_ids are globally unique across projects ---
    check("task ids globally unique across projects", web_task != api_task)

    # --- list_tasks: active scope shows only web's task; not api's ---
    res = T.handle_list_tasks({})
    body = text(res)
    check("list_tasks active echoes web", body.startswith("[project: web]\n"))
    check("list_tasks active shows web task", web_task in body)
    check("list_tasks active hides api task", api_task not in body)

    # --- list_tasks: project='all' shows both, grouped/labeled by project ---
    res = T.handle_list_tasks({"project": "all"})
    body = text(res)
    check("list_tasks all echoes 'all'", body.startswith("[project: all]\n"))
    check("list_tasks all shows web task", web_task in body)
    check("list_tasks all shows api task", api_task in body)
    check("list_tasks all labels web project", "project: web" in body)
    check("list_tasks all labels api project", "project: api" in body)

    # --- list_tasks: explicit project= other than active ---
    res = T.handle_list_tasks({"project": "api"})
    body = text(res)
    check("list_tasks explicit api echoes api", body.startswith("[project: api]\n"))
    check("list_tasks explicit api shows api task", api_task in body)
    check("list_tasks explicit api hides web task", web_task not in body)

    # --- task-addressed ops echo the TASK'S OWN project (no project= arg) ---
    # api_task lives in api, but active pointer is web -> echo must be api.
    res = T.handle_start_task({"task_id": api_task})
    check("start_task echoes task's own project (api)", text(res).startswith("[project: api]\n"))
    res = T.handle_read_task({"task_id": api_task})
    check("read_task echoes task's own project (api)", text(res).startswith("[project: api]\n"))
    res = T.handle_move_to_testing({"task_id": api_task, "test_plan": "click it"})
    check("move_to_testing echoes task's own project (api)", text(res).startswith("[project: api]\n"))
    res = T.handle_validate_task({"task_id": api_task})
    check("validate_task echoes task's own project (api)", text(res).startswith("[project: api]\n"))
    res = T.handle_freeze_task({"task_id": web_task, "reason": "deferred"})
    check("freeze_task echoes task's own project (web)", text(res).startswith("[project: web]\n"))
    res = T.handle_unfreeze_task({"task_id": web_task})
    check("unfreeze_task echoes task's own project (web)", text(res).startswith("[project: web]\n"))
    res = T.handle_trash_task({"task_id": web_task, "reason": "nope"})
    check("trash_task echoes task's own project (web)", text(res).startswith("[project: web]\n"))
    res = T.handle_move_to_todo({"task_id": web_task, "reason": "back"})
    check("move_to_todo echoes task's own project (web)", text(res).startswith("[project: web]\n"))

    # --- guard-path response (row fetched, project known) still echoes the
    #     task's own project. api_task is 'done' -> validate guard fires; active
    #     pointer is web, so echo must be api (the task's project, not active). ---
    res = T.handle_validate_task({"task_id": api_task})
    body = text(res)
    check("validate guard-path echoes task's own project (api)", body.startswith("[project: api]\n"))
    check("validate guard-path reports the guard message", "not on testing board" in body)

    # --- update_task: ordinary field updates, echoes the task's project ---
    res = T.handle_update_task({"task_id": web_task, "field": "priority", "value": "P0"})
    check("update_task field echoes task's project (web)", text(res).startswith("[project: web]\n"))
    conn = get_db()
    try:
        check(
            "update_task field wrote value",
            conn.execute("SELECT priority FROM tasks WHERE task_id = ?", (web_task,)).fetchone()[
                "priority"
            ]
            == "P0",
        )
    finally:
        conn.close()

    # --- update_task: reparent via field='project' ---
    res = T.handle_update_task({"task_id": web_task, "field": "project", "value": "api"})
    check("reparent echoes NEW project (api)", text(res).startswith("[project: api]\n"))
    conn = get_db()
    try:
        check(
            "reparent moved task to api",
            conn.execute("SELECT project_id FROM tasks WHERE task_id = ?", (web_task,)).fetchone()[
                "project_id"
            ]
            == api_id,
        )
    finally:
        conn.close()

    # --- update_task: reparent to unknown project does NOT write a bad FK ---
    res = T.handle_update_task({"task_id": web_task, "field": "project", "value": "nope-xyz"})
    check("reparent unknown project reports error", "not reparented" in text(res))
    conn = get_db()
    try:
        check(
            "reparent unknown left project_id unchanged (api)",
            conn.execute("SELECT project_id FROM tasks WHERE task_id = ?", (web_task,)).fetchone()[
                "project_id"
            ]
            == api_id,
        )
    finally:
        conn.close()

    # --- log_activity stamps the active project ---
    _set_active(P, get_db, web_id)
    res = T.handle_log_activity({"message": "worked on web"})
    check("log_activity echoes active project (web)", text(res).startswith("[project: web]\n"))
    res = T.handle_log_activity({"message": "worked on api", "project": "api"})
    check("log_activity explicit echoes api", text(res).startswith("[project: api]\n"))
    conn = get_db()
    try:
        check(
            "log_activity stamped active project (web)",
            conn.execute(
                "SELECT project_id FROM activity_log WHERE message = 'worked on web'"
            ).fetchone()["project_id"]
            == web_id,
        )
        check(
            "log_activity explicit stamped api",
            conn.execute(
                "SELECT project_id FROM activity_log WHERE message = 'worked on api'"
            ).fetchone()["project_id"]
            == api_id,
        )
    finally:
        conn.close()

    # --- report_security_findings stamps the resolved project ---
    res = T.handle_report_security_findings(
        {
            "findings": [{"title": "SQLi", "severity": "HIGH", "description": "bad query"}],
            "source": "audit",
            "project": "api",
        }
    )
    check("report_security_findings explicit echoes api", text(res).startswith("[project: api]\n"))
    conn = get_db()
    try:
        check(
            "security finding stamped explicit project (api)",
            conn.execute(
                "SELECT project_id FROM tasks WHERE title = 'SQLi'"
            ).fetchone()["project_id"]
            == api_id,
        )
    finally:
        conn.close()
    # default (no project=) stamps the active project (web)
    res = T.handle_report_security_findings(
        {"findings": [{"title": "XSS", "severity": "MEDIUM", "description": "reflected"}]}
    )
    check("report_security_findings default echoes active (web)", text(res).startswith("[project: web]\n"))
    conn = get_db()
    try:
        check(
            "security finding default stamped active (web)",
            conn.execute(
                "SELECT project_id FROM tasks WHERE title = 'XSS'"
            ).fetchone()["project_id"]
            == web_id,
        )
    finally:
        conn.close()

    # --- update_project_status writes the projects row (not a removed table) ---
    res = T.handle_update_project_status({"phase": "Build", "blockers": "None", "project": "api"})
    check("update_project_status explicit echoes api", text(res).startswith("[project: api]\n"))
    conn = get_db()
    try:
        check(
            "update_project_status wrote projects.phase for api",
            conn.execute("SELECT phase FROM projects WHERE id = ?", (api_id,)).fetchone()["phase"]
            == "Build",
        )
        # web (active) untouched by the explicit api update
        check(
            "explicit update left web phase at default",
            conn.execute("SELECT phase FROM projects WHERE id = ?", (web_id,)).fetchone()["phase"]
            == "Setup",
        )
    finally:
        conn.close()

    # default target = active project (web)
    res = T.handle_update_project_status({"phase": "Shipping"})
    check("update_project_status default echoes active (web)", text(res).startswith("[project: web]\n"))
    conn = get_db()
    try:
        check(
            "update_project_status default wrote active (web)",
            conn.execute("SELECT phase FROM projects WHERE id = ?", (web_id,)).fetchone()["phase"]
            == "Shipping",
        )
    finally:
        conn.close()

    # --- get_project_status reports the ACTIVE project's row + rollup ---
    res = T.handle_get_project_status({})
    body = text(res)
    check("get_project_status echoes active (web)", body.startswith("[project: web]\n"))
    check("get_project_status shows active phase", "Phase: Shipping" in body)
    check("get_project_status appends per-project rollup", "Projects:" in body)
    check("rollup lists web", "web: phase=Shipping" in body)
    check("rollup lists api", "api: phase=Build" in body)

    # explicit project= targets a non-active project's row
    res = T.handle_get_project_status({"project": "api"})
    body = text(res)
    check("get_project_status explicit echoes api", body.startswith("[project: api]\n"))
    check("get_project_status explicit shows api phase", "Phase: Build" in body)

    # get_project_status must NOT move the active pointer
    check(
        "get_project_status did not move the active pointer (still web)",
        _active(P, get_db) == web_id,
    )

    # --- onboarding handlers still work (untouched table) ---
    res = T.handle_get_onboarding_status({})
    check("get_onboarding_status still works", "Onboarding" in text(res))
    res = T.handle_update_onboarding({"field": "project_name", "value": "Demo"})
    check("update_onboarding still works", "project_name = Demo" in text(res))


def main():
    prev = Path.cwd()
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    try:
        run(root)
    finally:
        os.chdir(prev)
        # WAL sidecar files (.db-wal/.db-shm) can briefly hold a Windows lock
        # after connections close; don't let teardown mask the test result.
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if _failures:
        print(f"TASK-MANAGER: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"TASK-MANAGER: all {_checks} checks passed")


if __name__ == "__main__":
    main()
