import { open, readFile } from "node:fs/promises";
import { join } from "node:path";

import type { Entity } from "../entity/index.js";
import { lsTrackedFiles, type ExecFileFn } from "../git/index.js";
import {
  isContainedInWorkspace,
  stateKindOf,
  workspaceRelative,
  type ScopePaths,
} from "../layout/index.js";
import {
  ENTITY_SCHEMAS,
  ID_PREFIXES,
  keyOrderOf,
  prefixSpec,
  PROJECT_ARTICLE_BAND_SIZE,
  WORKSPACE_ARTICLE_BAND,
  type EntitySchema,
  type EntityType,
  type IdPrefixSpec,
} from "../registry/index.js";
import { makeFinding, type Finding } from "../schema/index.js";
import { isRecord, isStringArray } from "../shared/index.js";
import {
  buildMarkdown,
  canonicalYaml,
  splitFrontmatter,
} from "../yaml/index.js";

/** Scope reference stored in repair payloads (rebuildable into ScopePaths). */
export type ScopeRef =
  { kind: "workspace" } | { kind: "project"; slug: string; relPath: string };

/** Typed repair payloads carried on findings and consumed by `repair()`. */
export type RepairAction =
  | {
      action: "remint-id";
      type: "task" | "arc";
      scope: ScopeRef;
      oldId: string;
    }
  | { action: "set-fields"; type: EntityType; fields: Record<string, unknown> }
  | { action: "annotate-archived-ref"; type: EntityType; ref: string }
  | { action: "rewrite-canonical"; type: EntityType };

/** True for a well-formed `ScopeRef` (workspace, or project with strings). */
function isScopeRef(value: unknown): value is ScopeRef {
  if (!isRecord(value)) return false;
  if (value["kind"] === "workspace") return true;
  return (
    value["kind"] === "project" &&
    typeof value["slug"] === "string" &&
    typeof value["relPath"] === "string"
  );
}

/** True when `value` names an entity type the schema registry declares. */
function isEntityType(value: unknown): value is EntityType {
  return typeof value === "string" && value in ENTITY_SCHEMAS;
}

/**
 * Type guard for repair payloads read back off a finding. `Finding.repair`
 * is deliberately `unknown` (Article 003 extensibility) and `repair()` is
 * public, so payloads can arrive from a caller — e.g. an MCP layer
 * round-tripping findings through JSON. Each variant is therefore
 * discriminated on `action` and checked for exactly the fields that variant
 * uses; a payload that merely has a string `action` is not enough.
 */
export function isRepairAction(value: unknown): value is RepairAction {
  if (!isRecord(value)) return false;
  switch (value["action"]) {
    case "remint-id":
      return (
        (value["type"] === "task" || value["type"] === "arc") &&
        isScopeRef(value["scope"]) &&
        typeof value["oldId"] === "string"
      );
    case "set-fields":
      return isEntityType(value["type"]) && isRecord(value["fields"]);
    case "annotate-archived-ref":
      return isEntityType(value["type"]) && typeof value["ref"] === "string";
    case "rewrite-canonical":
      return isEntityType(value["type"]);
    default:
      return false;
  }
}

/** One scope's collected entities, ready for cross-checks. */
export interface ScopeEntities {
  scope: ScopePaths;
  scopeRef: ScopeRef;
  tasks: Entity[];
  arcs: Entity[];
  articles: Entity[];
  config?: Entity;
  curation?: Entity;
}

function rel(scope: ScopePaths, entity: Entity): string {
  return workspaceRelative(scope.workspaceRoot, entity.path);
}

/** Stable ordering for duplicate resolution: `created`, then path tiebreak. */
function byCreatedThenPath(a: Entity, b: Entity): number {
  const ca = typeof a.data["created"] === "string" ? a.data["created"] : "";
  const cb = typeof b.data["created"] === "string" ? b.data["created"] : "";
  return ca === cb ? a.path.localeCompare(b.path) : ca.localeCompare(cb);
}

/**
 * V-1: duplicate entity id — re-mint the younger (silent). Which entity a
 * `depends_on`/`arc` reference to the duplicated id meant is not mechanically
 * decidable post-merge, so every referencing entity gets a proposed companion
 * finding asking a human to confirm the target after the re-mint.
 */
export function checkDuplicateIds(scopeE: ScopeEntities): Finding[] {
  const findings: Finding[] = [];
  const byId = new Map<string, Entity[]>();
  for (const entity of [...scopeE.tasks, ...scopeE.arcs]) {
    const id = entity.data["id"];
    if (typeof id !== "string") continue;
    byId.set(id, [...(byId.get(id) ?? []), entity]);
  }
  for (const [id, group] of byId) {
    if (group.length < 2) continue;
    const sorted = [...group].sort(byCreatedThenPath);
    const elder = sorted[0] as Entity;
    for (const younger of sorted.slice(1)) {
      const repair: RepairAction = {
        action: "remint-id",
        type: younger.type === "arc" ? "arc" : "task",
        scope: scopeE.scopeRef,
        oldId: id,
      };
      findings.push(
        makeFinding(
          "V-1",
          "silent",
          rel(scopeE.scope, younger),
          `Duplicate id \`${id}\` (also in ${rel(scopeE.scope, elder)}); the younger file is re-minted`,
          { repair },
        ),
      );
    }
    // Companion findings: references to the duplicated id are ambiguous.
    for (const referrer of scopeE.tasks) {
      if (group.includes(referrer)) continue;
      const deps = referrer.data["depends_on"];
      const arcRef = referrer.data["arc"];
      const fields: string[] = [];
      if (isStringArray(deps) && deps.includes(id)) fields.push("depends_on");
      if (arcRef === id) fields.push("arc");
      for (const field of fields) {
        findings.push(
          makeFinding(
            "V-1",
            "proposed",
            rel(scopeE.scope, referrer),
            `Reference \`${id}\` in \`${field}\` is ambiguous after re-mint of a duplicate; confirm whether it should point at the surviving \`${id}\` (${rel(scopeE.scope, elder)}) or the re-minted entity`,
            {
              proposedFix: `Point \`${field}\` at the surviving \`${id}\` or at the re-minted id of ${rel(scopeE.scope, sorted[1] as Entity)}`,
            },
          ),
        );
      }
    }
  }
  return findings;
}

/** Article number band for a scope, from declared config (or undefined). */
export function articleBand(
  scopeE: ScopeEntities,
): { start: number; end: number } | undefined {
  if (scopeE.scope.kind === "workspace") return WORKSPACE_ARTICLE_BAND;
  const block = scopeE.config?.data["article_block"];
  if (!Number.isInteger(block)) return undefined;
  const start = block as number;
  return { start, end: start + PROJECT_ARTICLE_BAND_SIZE - 1 };
}

/** V-2/V-3: duplicate or out-of-band article numbers — renumber (silent). */
export function checkArticleNumbers(scopeE: ScopeEntities): Finding[] {
  const band = articleBand(scopeE);
  if (band === undefined) return [];
  const findings: Finding[] = [];
  const used = new Set<number>();
  const sorted = [...scopeE.articles].sort(byCreatedThenPath);
  const needsFix: { entity: Entity; rule: "V-2" | "V-3"; number: number }[] =
    [];
  for (const article of sorted) {
    const n = article.data["number"];
    if (!Number.isInteger(n)) continue; // Shape problems are V-8's job.
    const num = n as number;
    if (num < band.start || num > band.end) {
      needsFix.push({ entity: article, rule: "V-3", number: num });
    } else if (used.has(num)) {
      needsFix.push({ entity: article, rule: "V-2", number: num });
    } else {
      used.add(num);
    }
  }
  let cursor = band.start;
  for (const { entity, rule, number } of needsFix) {
    while (used.has(cursor) && cursor <= band.end) cursor++;
    if (cursor > band.end) {
      // Band saturated: renumbering silently would write out-of-band state.
      findings.push(
        makeFinding(
          rule,
          "proposed",
          rel(scopeE.scope, entity),
          `Article number ${number} cannot be repaired: band ${band.start}–${band.end} is full — widen the block or revoke an article`,
          {
            proposedFix:
              "Raise the scope's article block size or revoke an article to free a number",
          },
        ),
      );
      continue;
    }
    const next = cursor;
    used.add(next);
    const message =
      rule === "V-2"
        ? `Duplicate article number ${number} in scope \`${scopeE.scope.slug}\`; renumbering to ${next}`
        : `Article number ${number} outside band ${band.start}–${band.end}; renumbering to ${next}`;
    const repair: RepairAction = {
      action: "set-fields",
      type: "article",
      fields: { number: next },
    };
    findings.push(
      makeFinding(rule, "silent", rel(scopeE.scope, entity), message, {
        repair,
      }),
    );
  }
  return findings;
}

function archivedRefsOf(entity: Entity): string[] {
  const ext = entity.data["ext"];
  if (!isRecord(ext)) return [];
  const keel = ext["keel"];
  if (!isRecord(keel)) return [];
  const resolved = keel["resolved_by_archive"];
  return isStringArray(resolved) ? resolved : [];
}

/** Provider of the repo's full deleted-path set (fetched once per run). */
export type DeletedPathsProvider = () => Promise<readonly string[]>;

/**
 * V-4: dangling `depends_on` / `arc` refs — archive-annotate or propose.
 * Git history is fetched once per validate run through the memoized
 * `getDeletedPaths` provider and filtered per-ref in JS.
 */
export async function checkDanglingRefs(
  scopeE: ScopeEntities,
  getDeletedPaths: DeletedPathsProvider,
): Promise<Finding[]> {
  const findings: Finding[] = [];
  const known = new Set<string>();
  for (const entity of [...scopeE.tasks, ...scopeE.arcs]) {
    const id = entity.data["id"];
    if (typeof id === "string") known.add(id);
  }
  const refsOf = (entity: Entity): { field: string; ref: string }[] => {
    const out: { field: string; ref: string }[] = [];
    if (entity.type === "task") {
      const arc = entity.data["arc"];
      if (typeof arc === "string") out.push({ field: "arc", ref: arc });
      const deps = entity.data["depends_on"];
      if (isStringArray(deps)) {
        for (const ref of deps) out.push({ field: "depends_on", ref });
      }
    } else if (entity.type === "arc") {
      const members = entity.data["members"];
      if (isStringArray(members)) {
        for (const ref of members) out.push({ field: "members", ref });
      }
    }
    return out;
  };
  let deletedPaths: readonly string[] | undefined;
  for (const entity of [...scopeE.tasks, ...scopeE.arcs]) {
    const annotated = new Set(archivedRefsOf(entity));
    for (const { field, ref } of refsOf(entity)) {
      if (known.has(ref) || annotated.has(ref)) continue;
      if (deletedPaths === undefined) {
        try {
          deletedPaths = await getDeletedPaths();
        } catch (error) {
          // Without history we can neither annotate nor safely propose
          // removal — surface the failure once and stop V-4 for this scope.
          findings.push(
            makeFinding(
              "V-4",
              "proposed",
              "",
              `Git history lookup failed; dangling-reference resolution skipped: ${error instanceof Error ? error.message : String(error)}`,
            ),
          );
          return findings;
        }
      }
      const inHistory = deletedPaths.some((p) => p.includes(ref));
      const file = rel(scopeE.scope, entity);
      if (inHistory) {
        const repair: RepairAction = {
          action: "annotate-archived-ref",
          type: entity.type,
          ref,
        };
        findings.push(
          makeFinding(
            "V-4",
            "silent",
            file,
            `Reference \`${ref}\` in \`${field}\` was pruned to the archive; annotating resolved-by-archive`,
            { repair },
          ),
        );
      } else {
        findings.push(
          makeFinding(
            "V-4",
            "proposed",
            file,
            `Dangling reference \`${ref}\` in \`${field}\` (not in files or git history)`,
            {
              proposedFix: `Remove \`${ref}\` from \`${field}\` or restore the entity`,
            },
          ),
        );
      }
    }
  }
  return findings;
}

/** V-5: arc `members` ↔ task `arc` disagreement — union/order or propose. */
export function checkArcMembership(scopeE: ScopeEntities): Finding[] {
  const findings: Finding[] = [];
  const taskById = new Map<string, Entity>();
  for (const t of scopeE.tasks) {
    const id = t.data["id"];
    if (typeof id === "string") taskById.set(id, t);
  }
  const arcById = new Map<string, Entity>();
  for (const a of scopeE.arcs) {
    const id = a.data["id"];
    if (typeof id === "string") arcById.set(id, a);
  }
  const additions = new Map<string, string[]>(); // arc id → task ids to append
  const memberOf = new Map<string, Set<string>>(); // task id → arcs listing it

  for (const arc of scopeE.arcs) {
    const arcId = arc.data["id"];
    const members = arc.data["members"];
    if (typeof arcId !== "string" || !isStringArray(members)) continue;
    for (const memberId of members) {
      memberOf.set(memberId, (memberOf.get(memberId) ?? new Set()).add(arcId));
      const task = taskById.get(memberId);
      if (task === undefined) continue; // Missing targets are V-4's job.
      const back = task.data["arc"];
      if (back === arcId) continue;
      if (back === undefined || back === null) {
        const repair: RepairAction = {
          action: "set-fields",
          type: "task",
          fields: { arc: arcId },
        };
        findings.push(
          makeFinding(
            "V-5",
            "silent",
            rel(scopeE.scope, task),
            `Task \`${memberId}\` is a member of arc \`${arcId}\` but has no back-reference; setting \`arc: ${arcId}\``,
            { repair },
          ),
        );
      } else {
        findings.push(
          makeFinding(
            "V-5",
            "proposed",
            rel(scopeE.scope, task),
            `Task \`${memberId}\` claims arc \`${typeof back === "string" ? back : JSON.stringify(back)}\` but is listed in arc \`${arcId}\` — contradictory`,
            {
              proposedFix:
                "Decide which arc owns this task and align both sides",
            },
          ),
        );
      }
    }
  }

  for (const task of scopeE.tasks) {
    const taskId = task.data["id"];
    const arcRef = task.data["arc"];
    if (typeof taskId !== "string" || typeof arcRef !== "string") continue;
    const arc = arcById.get(arcRef);
    if (arc === undefined) continue; // Missing arcs are V-4's job.
    // A task already listed by some arc is either consistent or contradictory
    // (flagged above) — never silently unioned into a second arc.
    if ((memberOf.get(taskId)?.size ?? 0) > 0) continue;
    const members = arc.data["members"];
    if (!isStringArray(members)) continue;
    additions.set(arcRef, [...(additions.get(arcRef) ?? []), taskId]);
  }

  for (const [arcId, taskIds] of additions) {
    const arc = arcById.get(arcId);
    if (arc === undefined) continue;
    const members = arc.data["members"];
    const current = isStringArray(members) ? members : [];
    const merged = [...current, ...[...taskIds].sort()];
    const repair: RepairAction = {
      action: "set-fields",
      type: "arc",
      fields: { members: merged },
    };
    findings.push(
      makeFinding(
        "V-5",
        "silent",
        rel(scopeE.scope, arc),
        `Arc \`${arcId}\` is missing member(s) ${taskIds.sort().join(", ")} that reference it; union wins for membership`,
        { repair },
      ),
    );
  }
  return findings;
}

/** V-6: category/prefix mismatch — always proposed (legacy regex lesson). */
export function checkCategoryPrefix(
  scopeE: ScopeEntities,
  prefixes: readonly IdPrefixSpec[] = ID_PREFIXES,
): Finding[] {
  const findings: Finding[] = [];
  for (const task of scopeE.tasks) {
    const id = task.data["id"];
    const category = task.data["category"];
    if (typeof id !== "string" || typeof category !== "string") continue;
    const prefix = id.split("-")[0] ?? "";
    const spec = prefixSpec(prefix, prefixes);
    if (spec === undefined) {
      findings.push(
        makeFinding(
          "V-6",
          "proposed",
          rel(scopeE.scope, task),
          `Id prefix \`${prefix}\` is not in the declared prefix table`,
          {
            proposedFix:
              "Re-mint with a declared prefix or register the prefix",
          },
        ),
      );
    } else if (spec.category !== null && spec.category !== category) {
      findings.push(
        makeFinding(
          "V-6",
          "proposed",
          rel(scopeE.scope, task),
          `Id prefix \`${prefix}\` implies category \`${spec.category}\` but frontmatter says \`${category}\``,
          {
            proposedFix: `Recategorize to \`${spec.category}\` or re-mint under the matching prefix`,
          },
        ),
      );
    }
  }
  return findings;
}

/** V-10: project config `slug` must match its registry key. */
export function checkProjectSlug(scopeE: ScopeEntities): Finding[] {
  if (scopeE.scope.kind !== "project" || scopeE.config === undefined) return [];
  const slug = scopeE.config.data["slug"];
  if (typeof slug !== "string" || slug === scopeE.scope.slug) return [];
  return [
    makeFinding(
      "V-10",
      "proposed",
      rel(scopeE.scope, scopeE.config),
      `Project config slug \`${slug}\` differs from registry key \`${scopeE.scope.slug}\` (rename or copy-paste?)`,
      {
        proposedFix: `Align the config slug and the workspace.yaml projects key`,
      },
    ),
  ];
}

/** V-11: declared project paths must stay inside the workspace root. */
export function checkProjectPaths(
  workspaceRoot: string,
  projects: Readonly<Record<string, { path: string }>>,
  configFile: string,
): Finding[] {
  const findings: Finding[] = [];
  for (const [slug, decl] of Object.entries(projects)) {
    if (!isContainedInWorkspace(workspaceRoot, decl.path)) {
      findings.push(
        makeFinding(
          "V-11",
          "proposed",
          configFile,
          `Project \`${slug}\` declares path \`${decl.path}\` outside the workspace root`,
          {
            proposedFix:
              "Declare a path inside the workspace, or lift the rule via validation config",
          },
        ),
      );
    }
  }
  return findings;
}

/** Canonical on-disk content for a raw entity file, or why it cannot be. */
export function canonicalContentOf(
  raw: string,
  schema: EntitySchema,
):
  | { ok: true; content: string }
  | { ok: false; reason: "parse-error" | "comment-anchor" | "no-frontmatter" } {
  const keyOrder = keyOrderOf(schema);
  if (schema.format === "markdown") {
    const split = splitFrontmatter(raw);
    if (split === undefined) return { ok: false, reason: "no-frontmatter" };
    const result = canonicalYaml(split.yamlText, keyOrder);
    if (!result.ok) return { ok: false, reason: result.reason };
    return { ok: true, content: buildMarkdown(result.text, split.body) };
  }
  const result = canonicalYaml(raw, keyOrder);
  return result.ok
    ? { ok: true, content: result.text }
    : { ok: false, reason: result.reason };
}

/** V-12: non-canonical serialization — rewrite, or propose on anchor failure. */
export async function checkCanonicalSerialization(
  scopeE: ScopeEntities,
  schemas: Readonly<Record<EntityType, EntitySchema>>,
): Promise<Finding[]> {
  const findings: Finding[] = [];
  const entities: Entity[] = [
    ...scopeE.tasks,
    ...scopeE.arcs,
    ...scopeE.articles,
    ...(scopeE.config ? [scopeE.config] : []),
    ...(scopeE.curation ? [scopeE.curation] : []),
  ];
  for (const entity of entities) {
    let raw: string;
    try {
      raw = await readFile(entity.path, "utf8");
    } catch {
      continue;
    }
    const result = canonicalContentOf(raw, schemas[entity.type]);
    const file = rel(scopeE.scope, entity);
    if (!result.ok) {
      if (result.reason === "comment-anchor") {
        findings.push(
          makeFinding(
            "V-12",
            "proposed",
            file,
            "File is non-canonical but a hand-added comment cannot be safely re-anchored; skipping rewrite",
            {
              proposedFix:
                "Re-place the comment next to the key it describes, then re-run repair",
            },
          ),
        );
      }
      continue; // parse errors are the quarantine's job; no frontmatter is V-8's.
    }
    if (result.content !== raw) {
      const repair: RepairAction = {
        action: "rewrite-canonical",
        type: entity.type,
      };
      findings.push(
        makeFinding(
          "V-12",
          "silent",
          file,
          "File is not in canonical YAML serialization; rewriting canonically (content-identical)",
          { repair },
        ),
      );
    }
  }
  return findings;
}

const BINARY_SNIFF_BYTES = 8192;

/** Single-quotes a path for safe copy-paste into a POSIX shell. */
function shellQuote(path: string): string {
  return `'${path.replace(/'/g, `'\\''`)}'`;
}

/** Reads at most the first `BINARY_SNIFF_BYTES` of a file (never the whole). */
async function sniffHasNullByte(absPath: string): Promise<boolean> {
  const handle = await open(absPath, "r");
  try {
    const buffer = Buffer.alloc(BINARY_SNIFF_BYTES);
    const { bytesRead } = await handle.read(buffer, 0, BINARY_SNIFF_BYTES, 0);
    return buffer.subarray(0, bytesRead).includes(0);
  } finally {
    await handle.close();
  }
}

/** V-13: tracked derived/ephemera or binary files under state paths. */
export async function checkTrackedState(
  workspaceRoot: string,
  projectRelPaths: readonly string[],
  exec?: ExecFileFn,
): Promise<Finding[]> {
  const findings: Finding[] = [];
  let tracked: string[];
  try {
    tracked = await lsTrackedFiles(workspaceRoot, exec);
  } catch (error) {
    // Not-a-repo returns []; anything else must not silently disable V-13.
    findings.push(
      makeFinding(
        "V-13",
        "proposed",
        "",
        `git ls-files failed; tracked-state scan skipped: ${error instanceof Error ? error.message : String(error)}`,
      ),
    );
    return findings;
  }
  for (const path of tracked) {
    const kind = stateKindOf(path, projectRelPaths);
    if (kind === "derived" || kind === "ephemera") {
      findings.push(
        makeFinding(
          "V-13",
          "proposed",
          path,
          `Tracked ${kind} file — ${kind} must never be tracked (Article 004); never auto-removed`,
          {
            proposedFix: `\`git rm --cached ${shellQuote(path)}\` and verify .gitignore coverage`,
          },
        ),
      );
    } else if (kind === "truth") {
      try {
        if (await sniffHasNullByte(join(workspaceRoot, path))) {
          findings.push(
            makeFinding(
              "V-13",
              "proposed",
              path,
              "Binary file tracked under a state path — no binary state in git, ever (Article 004)",
              {
                proposedFix:
                  "Move the binary out of state paths or convert it to text",
              },
            ),
          );
        }
      } catch {
        // Tracked but absent from the working tree — nothing to sniff.
      }
    }
  }
  return findings;
}
