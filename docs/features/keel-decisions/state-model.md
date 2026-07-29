# Keel Decisions — State Model

**Version:** 1.0.0 | **Last Updated:** 2026-07-28 | **Status:** Approved
**Parent:** [Technical Decision Record hub](index.md)

## The Root Diagnosis

The legacy template's worst failures all traced to one cause: **six different kinds of state fused into one tracked binary SQLite file** (`claude.db`). Session ephemera shipped in releases (maintainer absolute paths leaked into distributions), history was destroyed by garbage collection (done tasks silently `DELETE`d, docs claimed "archived"), and any two branches or teammates touching state produced an unmergeable binary conflict with no documented resolution. The rewrite's state model begins by refusing that fusion.

## The State-Kind Taxonomy (ratified as Article 004, "State Declares Its Kind")

Every piece of persisted state must declare its kind; storage rules follow from classification:

| Kind | Examples | Storage rule |
|------|----------|--------------|
| **Truth** | tasks, arcs, articles, docs, config, registries, curated routing signals | Per-entity mergeable text, tracked in git |
| **Derived** | routing index, `board.md` projection, caches | Gitignored, rebuildable from truth, never tracked |
| **Ephemera** | active-scope pointer, reconciliation watermarks, review-gate evidence, credential profiles | Per-machine local, never tracked |
| **History** | everything that ever happened | Git itself; never destructively garbage-collected |

**Why:** each legacy bug maps to a category confusion. Ephemera tracked → leaks between machines and into releases. History treated as working state → destroyed by cleanup. Everything in one binary → unmergeable. Classification makes each failure structurally unrepresentable.

## Text-as-Truth: Architecture Choice

Considered: (A) per-entity text + derived index, (B) event sourcing / append-only log, (C) tracked DB with text round-trip, (D) = A + git-as-event-log. **Chosen: D.** Event sourcing (B) merges beautifully but demands compaction and fold-to-read machinery — "the kind of clever a 5-year support commitment regrets." C inherits drift between two representations. D gets A's mergeability plus B's audit trail for free, because `git log --follow state/tasks/<file>` *is* the entity's event history.

**Merge behavior (the G3 team requirement):** two branches touching different entities never conflict (different files). Same-entity conflicts are small, readable hunks (a frontmatter line vs a body paragraph often auto-merges). What git can't resolve, a post-merge **validate/repair pass** handles: dangling `depends_on` references, duplicate article numbers, ID collisions — each with a proposed (or silently applied, where safe) repair.

## File Formats

- **Human-facing entities (tasks, arcs, articles, docs): markdown + YAML frontmatter.** These are *documents with metadata*, not records — a task has prose acceptance criteria and accumulated notes; an article has Context/Rule/Consequences prose. Frontmatter gives machines the structured fields; the body stays a first-class diff/merge surface; GitHub renders it, so state is browsable with zero tooling; a non-AI teammate can edit it with any editor.
- **Purely structural records (config, manifests, registries, model overlays): YAML/JSON.**
- **Size limits measure the prose body only, excluding frontmatter** (Ben's refinement) — metadata growth must never pressure content cuts. Health checks report both numbers; only the body counts.

Example task file `state/tasks/T-k7f3m-fix-token-refresh.md`:

```markdown
---
id: T-k7f3m
status: working
category: bug
priority: P1
arc: A-9dwq2
assignee: ben
depends_on: [T-p2n8x]
provenance: user
---
Users see stale prices after checkout when the token refresh races the cart reload.

## Acceptance
- Refresh no longer races; prices correct on first render after checkout.

## Notes
- 07-28: reproduced on staging; suspect the retry backoff resets the cache key.
```

A PR closing this task shows a one-line status diff plus the closing note — state review rides code review.

## Routing: Where Truth Lives vs Where Queries Go

The sorting rule: **anything computable from the repo is derived (never tracked); anything human-curated is truth, stored as close as possible to the thing it describes.**

| Signal | Kind | Location |
|--------|------|----------|
| Doc curated keywords, source-path mappings, `load_at_start` | Truth | The doc's own frontmatter |
| Doc auto-keywords (headings) | Derived | Index only |
| Code auto-signals (paths, exports, line counts) | Derived | Index only (most of code routing) |
| Code curated hints (module descriptions, extra keywords) | Truth | Sparse per-project overlay file (`state/routing/curation.yaml`) — only deliberate entries, merged over auto-derived at build |

**The query path never reads docs.** Queries hit only the compiled, gitignored index (local SQLite or flat JSON with precomputed scores) — identical query-time behavior to legacy, except the index is now provably a cache.

**Index lifecycle — no service, no LLM:**
1. Setup script builds it once (mechanical: parse frontmatter, scan headings, walk source files — deterministic, sub-second, offline).
2. Write paths (`write_doc` etc.) update it incrementally as a side effect.
3. The reconciler rebuilds entries for externally-changed files at session start.
4. A lazy guard compares the index's recorded git HEAD + dirty-file mtimes before answering; stale or missing → rebuild first. Delete the index anytime; the next call heals it.

**Why tracking the index was rejected:** it changes whenever any doc/source changes, so a tracked index means every PR touches the same generated file — guaranteed merge conflicts between all branches, forever. The `claude.db` disease reintroduced. Rebuild cost (tens of ms) is strictly cheaper. Scaling note for giant monorepos: a prebuilt index could ship as a setup-time CI-artifact download — never as a tracked file. [Pending: scaling note only, not v1.]

**Division of labor over a doc's life:** the LLM's judgment (choosing curated keywords) is exercised once, at authoring time, and frozen into frontmatter as data; every rebuild and query afterward is mechanical. "Intelligence at write time, mechanics at read time" — the same seam as oval-game Article 012 (AI authors intent; deterministic code compiles it).

**Scoring:** legacy's weights (curated exact 1.5 / partial 0.75, auto 0.8 / 0.3, source-path 2.0) were folklore magic numbers scattered through code. Kept as defaults but (a) named in one declared config, (b) behind a **swappable scorer interface** — a registry entry, so embedding-based retrieval is an extension, not surgery.

## ID Scheme

**Killed:** sequential IDs (`T-042`) — two branches mint the same next number constantly (tasks are created mid-session, all day, on parallel branches); legacy even breaks at T-1000 (lexicographic `ORDER BY`). **Adopted:** type prefix + short random slug — `T-k7f3m`, `B-2xq9p`, `S-w4nd8` (~33M combinations at 5 base32 chars), kebab title in the filename for humans. Rejected alternatives: date-based (reintroduces ordering collisions), ULID/UUID (unspeakable, hostile filenames), title-hash (breaks on rename). Post-merge validator handles the near-never collision by re-minting. Type prefixes survive because gates use them ("S- tasks block release").

**Contrast with articles:** articles kept human-memorable numbers (see [governance.md](governance.md)) because their minting is rare and deliberate; tasks are minted constantly. Different minting rates → different schemes, each fitted honestly.

## Git as Archive; Silent Pruning; Retrieval

- **Hygiene and retention are separate knobs** (legacy fused them). Done tasks are pruned from working state after a declared retention window — per-board data; the **freezer never auto-prunes** (deferral is a promise).
- **Pruning is a silent side effect** (Ben's override of the initial propose-first design): it's housekeeping, provably reversible, and housekeeping that asks permission is nagging. The prune is a `git rm` in a normal commit — content, edit history, and the pruning moment all remain in git forever.
- **An archive-lookup tool** searches pruned items by keyword/date/type and resurrects content from git history — neither user nor agent needs git archaeology, and pruned state stays *inspectable* (Article 005).
- **The activity-log table dies:** git commits touching state files *are* the activity log — richer, attributed, free. "Recent activity" is a projection over `git log`.

Example: months later — "didn't we try optimistic locking and back it out?" The task was pruned in week 3. `archive-lookup "optimistic locking"` surfaces the full task file with the failure notes from git history in seconds. The board never carried the clutter; history never lost the answer.

## The board.md Projection

`board.md` is **re-rendered on every board mutation** as an engine side effect (plus session start, covering external changes) — pure string-building over text state, zero LLM, zero tokens, milliseconds. It exists **for the human with an editor open** (VS Code markdown preview auto-refreshes); the agent never reads it (agents query state tools); T-002's visual tool is the eventual interactive surface. Three consumers, one truth, each at the right cost. Contents: per-scope board sections (workspace scope first-class), a Mermaid dependency graph (kept — dependencies are genuinely graph-shaped), no Gantt (legacy's faked "3-day" durations — a chart with invented data is worse than no chart). The legacy edit-block hook dies: there's nothing to protect when regeneration is free.
