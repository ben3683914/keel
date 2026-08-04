import { readFile, realpath } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";

import {
  listEntities,
  readEntity,
  rewriteEntityFile,
  type Entity,
} from "../entity/index.js";
import { deletedPathsMatching, type ExecFileFn } from "../git/index.js";
import { mintId, type ClockFn, type RandomFn } from "../id/index.js";
import {
  isContainedInWorkspace,
  projectScope,
  workspaceRelative,
  workspaceScope,
  type ScopePaths,
} from "../layout/index.js";
import {
  ENTITY_SCHEMAS,
  ruleSpec,
  VALIDATION_RULES,
  type ValidationRuleSpec,
} from "../registry/index.js";
import { makeFinding, type Finding } from "../schema/index.js";
import { atomicWrite, isContained, isRecord } from "../shared/index.js";
import {
  canonicalContentOf,
  checkArcMembership,
  checkArticleNumbers,
  checkCanonicalSerialization,
  checkCategoryPrefix,
  checkDanglingRefs,
  checkDuplicateIds,
  checkProjectPaths,
  checkProjectSlug,
  checkTrackedState,
  isRepairAction,
  type RepairAction,
  type ScopeEntities,
  type ScopeRef,
} from "./rules.js";

/** Options for a validation run. */
export interface ValidateOptions {
  /** Absolute workspace root — always explicit, never `process.cwd()`. */
  workspaceRoot: string;
  /** Limit to one scope: `"workspace"` or a project slug. Default: all. */
  scope?: string;
  /** Git seam for V-4 / V-13. */
  exec?: ExecFileFn;
  /**
   * Declared validation rule config. Passing a copy without an entry lifts
   * that rule (e.g. `workspace-internal-paths`) — data, not surgery.
   */
  rules?: readonly ValidationRuleSpec[];
}

/** Repair mode: apply the silent class, or materialize proposals only. */
export type RepairMode = "silent" | "proposed";

/** Dependencies for a repair run (seams keep tests deterministic). */
export interface RepairOptions {
  workspaceRoot: string;
  /** Randomness seam for V-1 re-minting. */
  rng?: RandomFn;
  /** Clock seam (re-minting keeps the original `created`; seam for parity). */
  clock?: ClockFn;
}

/** Outcome of a repair run. */
export interface RepairResult {
  /** Silent repairs actually applied to disk. */
  applied: Finding[];
  /** Proposed findings, returned as structured data (findings→task pipeline is a later task). */
  proposals: Finding[];
  /** Findings not handled in this mode (or whose application failed). */
  skipped: Finding[];
}

/**
 * True when a declared project path exists and its realpath escapes the
 * realpath'd workspace root (symlinked project folder).
 */
async function scopeEscapesViaSymlink(
  workspaceRoot: string,
  declaredPath: string,
): Promise<boolean> {
  let realScope: string;
  try {
    realScope = await realpath(resolve(workspaceRoot, declaredPath));
  } catch {
    return false; // Not on disk yet — the lexical check is all there is.
  }
  let realRoot: string;
  try {
    realRoot = await realpath(resolve(workspaceRoot));
  } catch {
    realRoot = resolve(workspaceRoot);
  }
  return !isContained(realRoot, realScope);
}

const declaredProjects = (
  config: Entity | undefined,
): Record<string, { path: string }> => {
  const projects = config?.data["projects"];
  const out: Record<string, { path: string }> = {};
  if (typeof projects !== "object" || projects === null) return out;
  for (const [slug, decl] of Object.entries(projects)) {
    const path = (decl as { path?: unknown } | null)?.path;
    if (typeof path === "string") out[slug] = { path };
  }
  return out;
};

// Note: docs/ trees are deliberately NOT collected or validated here — doc
// frontmatter validation is deferred by design to the routing/reconciler
// tasks (T-010+), which own doc discovery and staleness.
async function collectScope(
  scope: ScopePaths,
  scopeRef: ScopeRef,
): Promise<{ scopeE: ScopeEntities; readFindings: Finding[] }> {
  const readFindings: Finding[] = [];
  const tasks = await listEntities(scope, "task");
  const arcs = await listEntities(scope, "arc");
  const articles = await listEntities(scope, "article");
  readFindings.push(...tasks.findings, ...arcs.findings, ...articles.findings);
  const configType =
    scope.kind === "workspace" ? "workspace-config" : "project-config";
  const config = await readEntity({ scope, type: configType, id: "" });
  const curation = await readEntity({ scope, type: "curation", id: "" });
  readFindings.push(...config.findings, ...curation.findings);
  const scopeE: ScopeEntities = {
    scope,
    scopeRef,
    tasks: tasks.entities,
    arcs: arcs.entities,
    articles: articles.entities,
    ...(config.entity ? { config: config.entity } : {}),
    ...(curation.entity ? { curation: curation.entity } : {}),
  };
  return { scopeE, readFindings };
}

function sortFindings(
  findings: Finding[],
  rules: readonly ValidationRuleSpec[],
): Finding[] {
  const order = new Map(rules.map((r, i) => [r.rule, i]));
  return [...findings].sort((a, b) => {
    const ra = order.get(a.rule) ?? rules.length;
    const rb = order.get(b.rule) ?? rules.length;
    if (ra !== rb) return ra - rb;
    if (a.file !== b.file) return a.file.localeCompare(b.file);
    return a.message.localeCompare(b.message);
  });
}

/**
 * Runs the full V-1..V-13 table over the workspace (or one scope) and returns
 * findings — silent-repairable, proposed, and quarantined. Read-only: apply
 * fixes with `repair()`. Idempotent with repair: a second validate over
 * repaired state finds nothing (Article 002).
 */
export async function validate(options: ValidateOptions): Promise<Finding[]> {
  const { workspaceRoot, exec } = options;
  const rules = options.rules ?? VALIDATION_RULES;
  const enabled = (rule: string): boolean =>
    ruleSpec(rule, rules) !== undefined;
  const findings: Finding[] = [];

  const ws = workspaceScope(workspaceRoot);
  const wsCollected = await collectScope(ws, { kind: "workspace" });
  const projects = declaredProjects(wsCollected.scopeE.config);
  const configFile = workspaceRelative(workspaceRoot, ws.configPath);

  if (enabled("V-11")) {
    findings.push(...checkProjectPaths(workspaceRoot, projects, configFile));
  }

  const scopes: { scopeE: ScopeEntities; readFindings: Finding[] }[] = [];
  if (options.scope === undefined || options.scope === "workspace") {
    scopes.push(wsCollected);
  }
  const projectRelPaths: string[] = [];
  for (const [slug, decl] of Object.entries(projects)) {
    // Never walk a path that escapes the workspace (V-11 already flagged it).
    if (!isContainedInWorkspace(workspaceRoot, decl.path)) continue;
    // Lexical containment can be defeated by a symlinked project folder:
    // realpath the scope root (when it exists) and re-check against the
    // realpath'd workspace root before collecting anything from it.
    const escaped = await scopeEscapesViaSymlink(workspaceRoot, decl.path);
    if (escaped) {
      if (enabled("V-11")) {
        findings.push(
          makeFinding(
            "V-11",
            "proposed",
            configFile,
            `Project \`${slug}\` path \`${decl.path}\` resolves outside the workspace root via a symbolic link; scope skipped`,
            {
              proposedFix:
                "Replace the symlink with a real folder inside the workspace",
            },
          ),
        );
      }
      continue;
    }
    projectRelPaths.push(decl.path);
    if (options.scope !== undefined && options.scope !== slug) continue;
    const scope = projectScope(workspaceRoot, slug, decl.path);
    scopes.push(
      await collectScope(scope, { kind: "project", slug, relPath: decl.path }),
    );
  }

  // Git history is fetched at most once per validate run (V-4), lazily.
  let deletedPathsCache: Promise<readonly string[]> | undefined;
  const getDeletedPaths = (): Promise<readonly string[]> => {
    deletedPathsCache ??= deletedPathsMatching(workspaceRoot, "", exec);
    return deletedPathsCache;
  };

  for (const { scopeE, readFindings } of scopes) {
    findings.push(...readFindings.filter((f) => enabled(f.rule)));
    if (enabled("V-1")) findings.push(...checkDuplicateIds(scopeE));
    if (enabled("V-2") || enabled("V-3")) {
      findings.push(
        ...checkArticleNumbers(scopeE).filter((f) => enabled(f.rule)),
      );
    }
    if (enabled("V-4")) {
      findings.push(...(await checkDanglingRefs(scopeE, getDeletedPaths)));
    }
    if (enabled("V-5")) findings.push(...checkArcMembership(scopeE));
    if (enabled("V-6")) findings.push(...checkCategoryPrefix(scopeE));
    if (enabled("V-10")) findings.push(...checkProjectSlug(scopeE));
    if (enabled("V-12")) {
      findings.push(
        ...(await checkCanonicalSerialization(scopeE, ENTITY_SCHEMAS)),
      );
    }
  }

  if (enabled("V-13")) {
    findings.push(
      ...(await checkTrackedState(workspaceRoot, projectRelPaths, exec)),
    );
  }

  // Resolve ruleId/severity from the ACTIVE rule config, so overrides passed
  // via `options.rules` take effect as data — even for findings produced by
  // the read path, which only knows the shipped defaults.
  const remapped = findings.map((f) => {
    const spec = ruleSpec(f.rule, rules);
    return spec === undefined
      ? f
      : { ...f, ruleId: spec.id, severity: spec.severity };
  });
  return sortFindings(remapped, rules);
}

async function applyRepair(
  file: string,
  action: RepairAction,
  options: RepairOptions,
): Promise<{ renamedTo?: string }> {
  const abs = join(options.workspaceRoot, file);
  // A finding whose file escapes the workspace is never applied; throwing
  // here routes it into repair()'s existing skip path.
  if (!isContained(options.workspaceRoot, abs)) {
    throw new Error(`Repair target escapes the workspace root: ${file}`);
  }
  switch (action.action) {
    case "remint-id": {
      // A caller-supplied payload can name any project path; minting reads
      // the scope's entity directory, so containment is checked before the
      // scope is constructed (out-of-tree reads, not just writes).
      if (
        action.scope.kind === "project" &&
        !isContainedInWorkspace(options.workspaceRoot, action.scope.relPath)
      ) {
        throw new Error(
          `Repair scope path escapes the workspace root: ${action.scope.relPath}`,
        );
      }
      const scope =
        action.scope.kind === "workspace"
          ? workspaceScope(options.workspaceRoot)
          : projectScope(
              options.workspaceRoot,
              action.scope.slug,
              action.scope.relPath,
            );
      const prefix = action.oldId.split("-")[0] ?? "";
      const minted = await mintId(prefix, scope, {
        ...(options.rng ? { rng: options.rng } : {}),
        ...(options.clock ? { clock: options.clock } : {}),
      });
      const newName = basename(abs).replace(action.oldId, minted.id);
      await rewriteEntityFile(
        options.workspaceRoot,
        abs,
        action.type,
        (data) => ({ ...data, id: minted.id }),
        join(dirname(abs), newName),
      );
      return {
        renamedTo: join(dirname(file), newName).split("\\").join("/"),
      };
    }
    case "set-fields":
      await rewriteEntityFile(
        options.workspaceRoot,
        abs,
        action.type,
        (data) => ({
          ...data,
          ...structuredClone(action.fields),
        }),
      );
      return {};
    case "annotate-archived-ref":
      await rewriteEntityFile(
        options.workspaceRoot,
        abs,
        action.type,
        (data) => {
          const ext = isRecord(data["ext"]) ? { ...data["ext"] } : {};
          const keel = isRecord(ext["keel"]) ? { ...ext["keel"] } : {};
          const existing = keel["resolved_by_archive"];
          const refs = Array.isArray(existing)
            ? existing.filter((r): r is string => typeof r === "string")
            : [];
          if (!refs.includes(action.ref)) refs.push(action.ref);
          refs.sort();
          return {
            ...data,
            ext: { ...ext, keel: { ...keel, resolved_by_archive: refs } },
          };
        },
      );
      return {};
    case "rewrite-canonical": {
      const raw = await readFile(abs, "utf8");
      const result = canonicalContentOf(raw, ENTITY_SCHEMAS[action.type]);
      if (!result.ok) {
        throw new Error(`Cannot canonicalize ${file}: ${result.reason}`);
      }
      await atomicWrite(options.workspaceRoot, abs, result.content);
      return {};
    }
    default:
      // Unreachable for well-formed payloads (isRepairAction discriminates
      // every variant); explicit so an added action fails closed loudly
      // rather than by accident during a refactor.
      throw new Error(
        `Unknown repair action: ${String((action as { action?: unknown }).action)}`,
      );
  }
}

/**
 * Applies the silent repair class (mode `"silent"`), or materializes proposed
 * findings as structured data without touching disk (mode `"proposed"`).
 * Repair is idempotent: a second validate+repair pass over repaired state
 * finds nothing (Article 002). Silent repairs are ordinary file edits meant
 * to be committed — the repair moment itself is archived history.
 */
export async function repair(
  findings: readonly Finding[],
  mode: RepairMode,
  options: RepairOptions,
): Promise<RepairResult> {
  const proposals = findings.filter((f) => f.mode === "proposed");
  if (mode === "proposed") {
    return {
      applied: [],
      proposals,
      skipped: findings.filter((f) => f.mode !== "proposed"),
    };
  }
  const applied: Finding[] = [];
  const skipped: Finding[] = findings.filter(
    (f) => f.mode !== "proposed" && f.mode !== "silent",
  );
  // Files renamed earlier in this run (V-1 re-mints) are remapped so later
  // co-located repairs still find their target.
  const renames = new Map<string, string>();
  for (const finding of findings.filter((f) => f.mode === "silent")) {
    if (!isRepairAction(finding.repair)) {
      skipped.push(finding);
      continue;
    }
    const file = renames.get(finding.file) ?? finding.file;
    try {
      const outcome = await applyRepair(file, finding.repair, options);
      if (outcome.renamedTo !== undefined) {
        renames.set(file, outcome.renamedTo);
      }
      applied.push(finding);
    } catch {
      skipped.push(finding);
    }
  }
  return { applied, proposals, skipped };
}
