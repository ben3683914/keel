# Keel Decisions — Governance & Constitution

**Version:** 1.0.0 | **Last Updated:** 2026-07-28 | **Status:** Approved
**Parent:** [Technical Decision Record hub](index.md)

## The Constitution System (kept — strongest conviction of the walkthrough)

Numbered, ratified rules modeled on legislation: each article carries **Context** (why it exists), **Rule** (binding text), **Consequences** (what breaks without it), **Enforcement** (how it's checked), with lifecycle `proposed → ratified → amended → re-affirmed / revoked`. Two tiers: workspace articles bind every project; projects add their own.

**Why it's the crown jewel:** decisions decay in AI-assisted work — forgotten after `/clear`, re-litigated by the next model, violated by the next teammate. The constitution turns "we decided X" into a durable, versioned, *enforced* artifact with its reasoning attached. The proof case is the oval game's Article 030 story: articles 015/018 said "no hardcoded scenario content"; 130+ tasks violated them anyway; when the audit finally ran, *the articles were the checklist* that caught everything in one session — and the lesson became new law (030) rather than a doc nobody reads.

**Vocabulary note (open item):** in constitutional practice, *articles* are original provisions; *amendments* are changes to them. Legacy overloaded `amended` as a status meaning both "mid-edit" and "locally diverged." Cleaner model: articles with statuses `proposed / ratified / revoked`, amendments as first-class *events* in an article's history. [Pending: final vocabulary pass in the governance feature design.]

## In-Band Injection + Capability Compensation (kept + extended)

Rules are re-asserted **inside tool responses at the moment of relevance**, not just trusted from a system prompt — attention decays over a long context; rules injected near the point of action stay effective. Category filtering keeps token cost proportional.

**The extension (Ben's):** injection is also the **compensation layer** for harness capability gaps. Adapters declare capabilities ("Claude Code: commit hooks, stop hooks; Codex: neither"); the core consults that matrix when composing responses. On Claude Code the commit gate physically blocks, so injection stays lean; on Codex the same tool response carries "⚠ reviews for this task have not run — pipeline requires code → docs → security → tests before commit," because assertion is all that harness offers. Same declared rules, one injection engine, per-harness intensity. This makes injection the **most harness-portable enforcement Keel has** — every MCP-speaking harness receives tool responses.

**Self-describing filtering (added after a live mistake):** during this very session, the category-filtered injection showed 9 of 11 workspace articles and the assistant mistook the filtered view for the whole. Rule: injections must state their own filtering — `Constitution (9 of 11 shown — category-filtered; list_articles for all)`. A partial view must never masquerade as complete.

**Trigger-based routing (refinement):** once articles declare triggers (Article 006 below), injection targets rules whose triggers match the current activity, not just coarse categories.

## The Numbering Standard (full derivation)

Ben's requirement: `workspace/001` and `project/001` coexisting is unacceptable — a number said aloud must mean one thing. The design evolved across three proposals in-session:

1. First proposal: globally unique sequence + reserved band for framework articles. Rejected as too rigid alone.
2. Ben's counter: pure next-available assignment resolved by the receiving workspace — maximally adaptive, but sacrifices cross-workspace consistency for the always-used framework articles.
3. Ben's synthesis (adopted, then banded): **consistency where earned, adaptation everywhere else** — plus **scope-banded blocks**.

**Final standard:**

| Rule | Detail |
|------|--------|
| Banded blocks | Workspace scope owns 1–99; each project gets a 100-block at creation (100–199, 200–299, …), recorded in that project's config; overflow allocates the next free block |
| Framework preferred numbers | Framework-shipped articles carry a *preferred* number low in 1–99 — honored if free, **adapted if not** (assign next available; no error, no migration) |
| Local assignment | Everything else takes next-available within its scope's block; packs number into wherever they're installed |
| Identity vs alias | **Slugs are identity** (`source_id`, provenance-carrying); numbers are local display aliases |
| Self-reference | Shipped content (tutorials, rubrics, docs) references articles **by slug only**; the render layer resolves to the local number at display time — a number literal in shipped content would be wrong per-workspace (Article 001 applied to ourselves) |
| Collisions | Same-scope parallel branches minting the same number → post-merge repair renumbers the later-ratified one (a one-line frontmatter edit; slug references never break). Different scopes can't collide by construction — the band *is* the partition |

Bonus: the band encodes jurisdiction — "Article 214" is visibly project-2 law before any lookup.

## The Six Ratified Articles (ai-development-template/001–006, 2026-07-28)

Proposed and ratified in-session to govern the rewrite work itself; also the prototype for Keel's shipped base set.

| # | Article | Source | Core mandate |
|---|---------|--------|--------------|
| 001 | Engine/Data Separation | oval 015 | No workspace/harness/model literals in engine code; behavior arrives as validated data |
| 002 | Idempotent, Reproducible Operations | oval 014 | Every operation converges on re-run; derived state rebuildable byte-equivalently; no wall-clock/randomness in outcomes |
| 003 | Registries Over Bespoke Code Paths | oval 018 | New capabilities are registry entries + data, never new hardcoded paths; framework and user entries share mechanisms |
| 004 | State Declares Its Kind | session | The taxonomy (see [state-model.md](state-model.md)); no binary state in git, ever |
| 005 | Every State Kind Is Inspectable | oval 022 | New persisted state ships with its inspection surface in the same change; reads never mutate |
| 006 | Articles Must Name Their Trigger | oval 030 | No ratification without a concrete, checkable enforcement trigger; "the failure mode was a missing trigger, not missing law" |

**Why 006 is the meta-keystone:** it encodes the oval game's hard-won lesson that principles without triggers decay silently for 130 tasks. It also gives feature toggles something real to grab — enforcing an article *means* wiring its declared trigger — and it's why reviewer rubrics can assemble from articles (see [workflow.md](workflow.md)): trigger-matched articles *are* the checklist.

## Article Packs

Not every good article is universal — oval 012's AI-boundary rule (model output enters authoritative state only through schema-validated tools) matters enormously for AI-integrated products, not at all for a static site. So: a **small universal base set** + optional, versioned **article packs** (AI-boundaries, web-security, …) offered during onboarding based on interview answers, toggleable like features, delivered/updated through the update channel. Packs number into the local scope at install; pack slugs carry cross-workspace identity. [Pending: promotion of pack numbers into a reserved band if community vocabulary demand emerges.]

## Cross-Repo Identity & Update Behavior

Every article carries a provenance-bearing slug (`source_id`): framework-shipped vs project-authored. On framework updates, shipped articles upsert **by slug**; locally amended or revoked articles are detected and **respected, never clobbered** — local divergence is a first-class state, reported rather than overwritten. This generalizes the single best mechanism in the legacy system (its constitution `source_id`) to Keel's everything-has-provenance model (G10).
