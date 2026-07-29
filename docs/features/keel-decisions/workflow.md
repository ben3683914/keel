# Keel Decisions — Workflow, Boards & Reviews

**Version:** 1.0.0 | **Last Updated:** 2026-07-28 | **Status:** Approved
**Parent:** [Technical Decision Record hub](index.md)

## Task Boards (kept)

States: `todo → working → awaiting-validation → done`, plus **freezer** (deliberately deferred — parked, not abandoned) and **trash** (soft-deleted, recoverable). The state-machine framing is what makes enforcement possible: "can't commit while the task is unvalidated" only means something if task state is machine-readable.

- **Freezer defense:** without a first-class "deferred" state, parked ideas pollute todo until deleted in frustration, or die in trash. Deferral-as-state preserves the *decision* ("not now, on purpose") — exactly the kind of decision otherwise re-litigated every session. Freezer never auto-prunes.
- **Renamed handoff state (refinement):** legacy's `testing` actually meant "awaiting *user* validation" — a handoff, not a machine state. Keel models it as `awaiting-validation` with an assignee, so boards read truthfully in team use.
- **Category is explicit, classification still automatic** (bug-detection regexes killed): the agent sets category from *understanding* the request ("users see stale prices" → bug); pipelines set it structurally (security findings are born `S-`); humans pick it in tools; the schema validator rejects missing categories; a health audit *proposes* recategorizations — never silent. Legacy's `_looks_like_bug` regexes guessed invisibly ("Fix typo in error-handling docs" → silently became a bug, inflating bug counts); silent magic corrodes trust in every other automation.

## Arcs (G17 — new)

First-class task grouping: an arc is a per-entity text file with a name, an **intent statement**, an ordered member list, and notes. Rationale (Ben's oval-game observation): the AI groups tasks into coherent arcs well *while immersed in a system* — meaning the grouping lives in ephemeral context and gets re-derived every session. Arcs move that connective tissue into state: `depends_on` says "B needs A" but carries no why; an arc says "these nine tasks are the ingestion ceremony, in roughly this order, because of this design doc." A mid-altitude context on-ramp — G13's principle one level up. Boards render grouped by arc; creation can file into an arc; health checks notice orphaned/completed arcs. Arcs are narrative structure, **never sprints** — no dates, velocity, or burndowns (see non-goal 3).

## Tasks as Context On-Ramps (G13)

Work is always startable from a task without re-giving context; documentation accumulates gradually — capture-notes at creation, design later, implementation after. The task is the bridge across `/clear`, machines, and teammates. `[Pending: <question>]` markers in design docs carry their open question, auto-create linked tasks (deduped by doc+section identity, auto-closed when the section resolves), so incompleteness is legal but *untracked* incompleteness is not — honesty made cheap; a model that can write `[Pending]` doesn't have to hallucinate a decision.

## The Design Gate (kept)

For any new system/API/significant change, three ordered steps: **(a)** iterate one question at a time — each answer may change the next question; *no design doc yet*; **(b)** write the doc only when scope and trade-offs are agreed; **(c)** present it and get explicit go-ahead before implementation. The gate names and forbids a specific agent failure mode: producing a polished finished plan for rubber-stamping — 400 plausible lines the human skims and approves, with design errors discovered during implementation at 10x cost. One-at-a-time is information theory, not ceremony: batching structurally can't let answers reshape later questions. The T-001 interview itself demonstrated this (the audience answer changed what the coupling question meant; "let's talk state more" surfaced the taxonomy). **Threshold for "significant" is declared workspace data** — solo scratch loose, team repo tight.

## Review Pipeline as a Declared Stage Graph (changed)

Legacy hardcoded code → docs → security → tests across two hook files and three prose surfaces. Keel: the pipeline is **tracked config data per project** — which stages exist, order/dependencies, required vs advisory, what evidence each produces. Stages are feature-registry entries, so users add stages (licensing-review, accessibility-review) exactly the way Keel ships them.

**Validated live:** the same day this was decided, a second template tester independently expected tests *up front* rather than at the end. Under Keel that's his project's three-line config change (test-writing gate early, execution late — what TDD wants), while other projects keep test-last. No forks. This convergence of an organic user request with the design is the strongest validation the session produced.

**Stage executors (G16):** a stage declares its executor — `harness-subagent` (default) or `provider:<name>` — enabling **cross-model adversarial review** (e.g. GPT reviews what Claude wrote). Same-model review shares the author's priors: it finds the mistakes it wouldn't have made and misses exactly the ones it would. Cross-vendor review has uncorrelated blind spots. Missing credentials → visible fallback to subagent execution (adapt, don't enforce). Results flow into the same findings pipeline and evidence trail regardless of executor.

**Evidence is per-machine ephemera:** review acknowledgments attest to *this machine's* state; they don't travel (legacy tracking them is how counters leaked). Team-level assurance comes from CI state validation (see [collaboration.md](collaboration.md)).

## Reviewer Rubrics Assembled From Data (changed)

Legacy reviewers had TypeScript conventions baked into a "language-agnostic" system — a Python project got scolded about `any` usage. Keel keeps reviewer *identities* (code, docs, security, test — registry entries; users add more) but assembles each rubric at spawn time from layers:

1. **Core method** (shipped, stable): how to review, severity taxonomy, output contract
2. **Project conventions** (that project's config/conventions doc): naming, thresholds, idioms
3. **Trigger-matched constitution articles**: articles whose declared triggers say "check me at code review" arrive in the rubric automatically

Consequence: **governance and review converge.** Ratifying an article with a code-review trigger *is* editing the reviewer's checklist — one rule system, not two that can disagree. Example: a project ratifies "public functions carry docstrings" (trigger: code review); the next spawned reviewer flags violations citing the article by slug, rendered with that workspace's local number; other projects never see the rule.

## Findings → Tasks (kept, generalized)

One mechanism for *all* observations: security findings, review criticals, doc gaps, health-audit findings, reconciler discoveries → typed, severity-tagged tasks with structured provenance (which review, which commit, which file/line). Severity vocabulary is shared declared data. Gate interaction preserved from legacy (its subtle genius): "findings reported as tasks" satisfies the gate — deferral requires tracking, so the security gate is neither absolute (nobody runs it) nor toothless (report ignored). Provenance lets the reconciler auto-flag findings whose subject code was deleted. Example: ingestion review finds one HIGH (path traversal in archive extraction — fixed now) and two LOWs (tracked tasks; commit proceeds). Next planning, the LOWs sit on the board with reproduction context written at discovery time.

## Commit Gate: Parsed, Per-Segment, Actionable (changed)

Legacy regex-matched `git commit` against raw command strings — over-broad (`git checkout -b x && git commit …` rejected *whole*, so the branch never got created; the legacy CLAUDE.md carries a standing workaround warning — enforcement you must document workarounds for is prose wearing a code costume) and under-broad (`git -c k=v commit`, aliases, double spaces sail past). Keel's Claude-adapter gate **shell-parses** commands: per-segment verdicts in chains (the checkout runs; the commit gates), structural git-subcommand detection, and structured block messages: `commit gated [project: api]: security-review (missing), tests (missing); code-review ✓ docs-review ✓`. The message is actionable by agent and human alike. Gate behavior is fixture-tested in CI (commands + expected verdicts). Every false block teaches user and model to route around enforcement *generally* — gate precision is trust infrastructure.

## Orchestrator / Implementer Separation (kept, threshold loosened)

The main agent designs, decides, and is the **only writer of Keel state**; sub-agents implement and review but cannot touch state. Single-writer is what makes acknowledgments *evidence* ("reviewed by the agent reviewing its own code" is worthless) and keeps implementation detail out of the orchestrator's context (context economics applied to agents). **Loosened dogma:** legacy's absolute "never write source code directly" made a two-line fix into ceremony. Keel: the delegation threshold is declared data — orchestrator may directly make small changes below a defined scope; state-writing stays orchestrator-only at any scale; on harnesses with weak sub-agent support, the capability matrix degrades to direct implementation with reviews mattering more, not less.

## Workspace as Scope, Not Pseudo-Project (changed)

Legacy modeled the workspace as fake project row `id=1` that docs repeatedly begged users never to work on — an abstraction that leaked into rollups, health checks, and tutorials. Keel: the projects registry holds only real projects; scoped queries take `scope: workspace | project:<slug>`; workspace-scoped items (e.g. "bump CI Node version" — everyone's and no one's) are first-class citizens rendered at the top of `board.md`, health-checked and gated normally. No "skip row 1" special cases anywhere. Teams (G3) make cross-cutting items more common; they must not live somewhere users are warned away from.
