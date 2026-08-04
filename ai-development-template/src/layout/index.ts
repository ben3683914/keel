import { isAbsolute, join, normalize, relative, resolve, sep } from "node:path";

import type { EntityType } from "../registry/index.js";
import { deepFreeze } from "../shared/index.js";

/** The state-kind taxonomy (Article 004, State Declares Its Kind). */
export type StateKind = "truth" | "derived" | "ephemera";

/** One declared state-kind classification rule. */
export interface StateKindRule {
  readonly match: "exact" | "prefix" | "state-tree" | "docs-tree";
  readonly value: string;
  readonly kind: StateKind;
}

/**
 * Declared classification table for workspace-relative paths (Article 001:
 * layout is data). Order matters — first match wins.
 */
export const STATE_KIND_RULES: readonly StateKindRule[] = deepFreeze([
  { match: "prefix", value: ".keel/local/", kind: "ephemera" },
  { match: "prefix", value: ".keel/", kind: "derived" },
  { match: "exact", value: "board.md", kind: "derived" },
  { match: "state-tree", value: "state/", kind: "truth" },
  { match: "docs-tree", value: "docs/", kind: "truth" },
]);

/** Resolved paths for one scope (workspace or a registered project). */
export interface ScopePaths {
  readonly kind: "workspace" | "project";
  /** `"workspace"` for the workspace scope, else the project slug. */
  readonly slug: string;
  /** Absolute workspace root — always an explicit parameter, never cwd. */
  readonly workspaceRoot: string;
  /** Absolute root of the scope (workspace root or project folder). */
  readonly scopeRoot: string;
  readonly stateDir: string;
  readonly tasksDir: string;
  readonly arcsDir: string;
  readonly articlesDir: string;
  readonly configPath: string;
  readonly curationPath: string;
  readonly docsDir: string;
}

/** Derived/ephemera paths for a workspace (all gitignored, all rebuildable). */
export interface DerivedPaths {
  readonly keelDir: string;
  readonly derivedDir: string;
  readonly indexPath: string;
  readonly headPath: string;
  readonly localDir: string;
  readonly boardPath: string;
}

/** Resolves the workspace scope's paths from an explicit workspace root. */
export function workspaceScope(workspaceRoot: string): ScopePaths {
  const root = resolve(workspaceRoot);
  const stateDir = join(root, "state");
  return {
    kind: "workspace",
    slug: "workspace",
    workspaceRoot: root,
    scopeRoot: root,
    stateDir,
    tasksDir: join(stateDir, "tasks"),
    arcsDir: join(stateDir, "arcs"),
    articlesDir: join(stateDir, "articles"),
    configPath: join(stateDir, "config", "workspace.yaml"),
    curationPath: join(stateDir, "routing", "curation.yaml"),
    docsDir: join(root, "docs"),
  };
}

/**
 * Resolves a project scope's paths from the workspace root and the project's
 * declared relative path (from workspace.yaml `projects.<slug>.path`).
 */
export function projectScope(
  workspaceRoot: string,
  slug: string,
  projectRelPath: string,
): ScopePaths {
  const root = resolve(workspaceRoot);
  const scopeRoot = resolve(root, projectRelPath);
  const stateDir = join(scopeRoot, "state");
  return {
    kind: "project",
    slug,
    workspaceRoot: root,
    scopeRoot,
    stateDir,
    tasksDir: join(stateDir, "tasks"),
    arcsDir: join(stateDir, "arcs"),
    articlesDir: join(stateDir, "articles"),
    configPath: join(stateDir, "config.yaml"),
    curationPath: join(stateDir, "routing", "curation.yaml"),
    docsDir: join(scopeRoot, "docs"),
  };
}

/** Resolves the derived/ephemera paths for a workspace. */
export function derivedPaths(workspaceRoot: string): DerivedPaths {
  const root = resolve(workspaceRoot);
  const keelDir = join(root, ".keel");
  const derivedDir = join(keelDir, "derived");
  return {
    keelDir,
    derivedDir,
    indexPath: join(derivedDir, "index.json"),
    headPath: join(derivedDir, "head.json"),
    localDir: join(keelDir, "local"),
    boardPath: join(root, "board.md"),
  };
}

/** Directory (or fixed file path) holding a scope's entities of a type. */
export function entityDir(scope: ScopePaths, type: EntityType): string {
  switch (type) {
    case "task":
      return scope.tasksDir;
    case "arc":
      return scope.arcsDir;
    case "article":
      return scope.articlesDir;
    case "doc":
      return scope.docsDir;
    case "workspace-config":
    case "project-config":
      return scope.configPath;
    case "curation":
      return scope.curationPath;
  }
}

function normalizeRel(p: string): string {
  return normalize(p).split(sep).join("/");
}

/**
 * Classifies a workspace-relative path by state kind using the declared rule
 * table. `projectPaths` are the declared project folders (workspace-relative)
 * so `<project>/state/` and `<project>/docs/` classify as truth.
 * Returns undefined for paths the state layer does not own (e.g. src/).
 */
export function stateKindOf(
  workspaceRelPath: string,
  projectPaths: readonly string[] = [],
): StateKind | undefined {
  const p = normalizeRel(workspaceRelPath);
  const roots = ["", ...projectPaths.map((pp) => normalizeRel(pp) + "/")];
  for (const rule of STATE_KIND_RULES) {
    switch (rule.match) {
      case "exact":
        if (p === rule.value) return rule.kind;
        break;
      case "prefix":
        if (p.startsWith(rule.value)) return rule.kind;
        break;
      case "state-tree":
      case "docs-tree":
        for (const root of roots) {
          if (p.startsWith(root + rule.value)) return rule.kind;
        }
        break;
    }
  }
  return undefined;
}

/**
 * Canonicalizes a declared project path and checks containment within the
 * workspace root (V-11's check — the config path-traversal fence). Purely
 * lexical: declared paths may not exist yet.
 */
export function isContainedInWorkspace(
  workspaceRoot: string,
  declaredPath: string,
): boolean {
  const root = resolve(workspaceRoot);
  const target = resolve(root, declaredPath);
  const rel = relative(root, target);
  return rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
}

/** Converts an absolute path to a workspace-relative, `/`-separated path. */
export function workspaceRelative(
  workspaceRoot: string,
  absPath: string,
): string {
  return relative(resolve(workspaceRoot), absPath).split(sep).join("/");
}
