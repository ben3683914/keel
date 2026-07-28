**Session start checklist** (run in order, every session, before responding to any user message):
1. Call `get_startup_docs` — loads constitution and system context
2. Call `get_project_status` — loads current phase and active blockers
3. Call `check_code_health` and `check_doc_health`
4. If health checks report pending articles (awaiting ratification), present each to the user for ratification or revocation via `AskUserQuestion`
5. Suggest available tasks via `AskUserQuestion`
