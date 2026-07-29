# Keel Rewrite — Technical Decision Record (Hub)

**Version:** 1.0.0 | **Last Updated:** 2026-07-28 | **Status:** Approved

The complete, high-detail record of every decision made in the T-001 goal-setting interview (2026-07-28), with rationale and worked examples. The condensed companion is [keel-rewrite-goals.md](../keel-rewrite-goals.md) — read that first for the shape; read these when you need the *why* behind any piece, or when a future design conversation risks re-litigating something already settled.

Every decision here was made jointly with Ben in a one-question-at-a-time interview, per the design gate. Verdict convention used throughout the session: Ben's "agree" adopts the presented recommendation **including** its bundled refinements.

## Sub-Documents

| Document | Covers |
|----------|--------|
| [state-model.md](state-model.md) | State-kind taxonomy, text-as-truth, file formats, routing truth placement, index mechanics, ID scheme, git-as-archive, pruning, the `board.md` projection |
| [governance.md](governance.md) | Constitution system, article lifecycle, the numbering standard (full derivation), in-band injection + capability compensation, article packs, the six ratified articles |
| [workflow.md](workflow.md) | Boards, arcs, task lifecycle, design gate, review pipeline as declared stage graph, rubric assembly, findings→tasks, commit gate, orchestrator separation, workspace-as-scope |
| [platform.md](platform.md) | Neutral core + harness adapters, capability matrix, instruction shims and 3-layer assembly, model overlays, engine language decision, AI provider registry, command safety |
| [distribution.md](distribution.md) | Artifact shipping, update system (baseline three-way merge, channel format), provenance, onboarding + ingestion + self-cleanup, setup/doctor, verification-by-execution |
| [collaboration.md](collaboration.md) | Team workflow shapes with four worked scenarios, external-change reconciliation, PR-first optimization, CI state validation, task claiming, multi-repo seams |

## Session Provenance

- Legacy concept extraction: full Explore-agent report over PROJECT-TEMPLATE v2.5.0 (45 concepts, pain points, lifecycle map)
- Keep/change/kill walkthrough: 36 items, every verdict recorded with adopted refinements (16 kept / 14 changed / 6 killed)
- Base-article inspiration: the_oval_game constitution articles 012, 014, 015, 018, 022, 030
- Constitution: ai-development-template articles 001–006 proposed and ratified during the session
- Tasks: T-001 (this interview), T-002 (visual pipeline editor)
