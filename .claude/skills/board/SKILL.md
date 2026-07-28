---
name: board
description: Display the project board (active project by default) with task counts and active work
disable-model-invocation: true
---

Boards are per-project. Show the board for the **active project** by default, and
state which project that is.

1. Call `list_tasks` for working, testing, and todo boards
2. Show task counts per board
3. List all working and testing tasks with details
4. Show dependency relationships

Pass `project=<slug>` to view another project's board, or `project='all'` to
roll up tasks across every project. For a cross-project summary of phase and
counts, use `get_project_status`'s rollup instead.
