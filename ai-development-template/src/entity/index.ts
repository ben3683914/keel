import { readdir, readFile, unlink } from "node:fs/promises";
import { basename, join, resolve } from "node:path";

import { atomicWrite, isContained } from "../shared/index.js";

import {
  entityDir,
  workspaceRelative,
  type ScopePaths,
} from "../layout/index.js";
import {
  ENTITY_SCHEMAS,
  idPattern,
  keyOrderOf,
  type EntityType,
} from "../registry/index.js";
import {
  applyDefaults,
  makeFinding,
  validateBody,
  validateData,
  type Finding,
} from "../schema/index.js";
import {
  buildMarkdown,
  canonicalizeDocument,
  parseYaml,
  setPreservingComments,
  splitFrontmatter,
  stringifyCanonical,
} from "../yaml/index.js";
import { Document } from "yaml";

/** A parsed entity: typed data plus prose body, tied to its file. */
export interface Entity {
  type: EntityType;
  /** Absolute file path. */
  path: string;
  data: Record<string, unknown>;
  body: string;
}

/** Result of reading an entity: absent on not-found or quarantine. */
export interface ReadResult {
  entity?: Entity;
  findings: Finding[];
}

/** Result of listing a scope's entities: matches plus every finding seen. */
export interface ListResult {
  entities: Entity[];
  findings: Finding[];
}

/** Reference to an entity by scope, type, and identity. */
export interface EntityRef {
  scope: ScopePaths;
  type: EntityType;
  /** Task/arc id or article slug. Ignored for path-identity types. */
  id: string;
}

/** Filter for `listEntities`: partial data match or predicate. */
export type EntityFilter =
  Partial<Record<string, unknown>> | ((entity: Entity) => boolean);

/** Event passed to the `onWrite` side-effect hook. */
export interface WriteEvent {
  /** Absolute path written. */
  path: string;
  /** Previous path when the write renamed the file (retitle). */
  previousPath?: string;
  entity: Entity;
  scope: ScopePaths;
}

/** Options for `writeEntity`. */
export interface WriteOptions {
  /**
   * Side-effect hook seam: called after a successful atomic write. T-010
   * (index update) and T-011 (board render) attach here — the state layer
   * itself performs no derived-state side effects.
   */
  onWrite?: (event: WriteEvent) => void | Promise<void>;
}

/** Result of an engine write: rejected writes carry the finding list. */
export type WriteResult =
  | { ok: true; path: string; findings: Finding[] }
  | { ok: false; findings: Finding[] };

/** Input to `writeEntity`. */
export interface WriteEntityInput {
  scope: ScopePaths;
  type: EntityType;
  data: Record<string, unknown>;
  body?: string;
  /** Explicit target path — required for docs, ignored for fixed-path types. */
  path?: string;
}

/** Kebab-cases a title for the filename's human-courtesy suffix. */
export function kebabTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/, "");
}

async function readFileOrUndefined(path: string): Promise<string | undefined> {
  try {
    return await readFile(path, "utf8");
  } catch {
    return undefined;
  }
}

/**
 * Recursively lists `.md`/`.yaml` regular files under a directory (may be
 * absent). Symbolic links are never followed — a link under a state path is
 * reported so the validator can surface it, not silently read through.
 */
async function walkFiles(
  dir: string,
): Promise<{ files: string[]; symlinks: string[] }> {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return { files: [], symlinks: [] };
  }
  const files: string[] = [];
  const symlinks: string[] = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    const full = join(dir, entry.name);
    if (entry.isSymbolicLink()) {
      if (!entry.name.startsWith(".")) symlinks.push(full);
    } else if (entry.isDirectory()) {
      const nested = await walkFiles(full);
      files.push(...nested.files);
      symlinks.push(...nested.symlinks);
    } else if (
      entry.isFile() &&
      /\.(md|ya?ml)$/.test(entry.name) &&
      !entry.name.startsWith(".")
    ) {
      files.push(full);
    }
  }
  return { files, symlinks };
}

/**
 * Generic by-path read (the Article 005 inspection floor: serialize any
 * entity by path). Malformed files become findings, never crashes;
 * unparseable YAML quarantines the file with file/line and no entity.
 */
export async function readEntityByPath(
  path: string,
  type: EntityType,
  workspaceRoot: string,
): Promise<ReadResult> {
  const schema = ENTITY_SCHEMAS[type];
  const raw = await readFileOrUndefined(path);
  const relFile = workspaceRelative(workspaceRoot, path);
  if (raw === undefined) return { findings: [] };

  let yamlText: string;
  let body = "";
  if (schema.format === "markdown") {
    const split = splitFrontmatter(raw);
    if (split === undefined) {
      // No frontmatter: legal for docs (no curated signals — adapt, don't
      // enforce); for state entities every required field is missing.
      const data: Record<string, unknown> = {};
      const findings =
        type === "doc" ? [] : validateData(data, schema, relFile, "on-disk");
      return { entity: { type, path, data, body: raw }, findings };
    }
    yamlText = split.yamlText;
    body = split.body;
  } else {
    yamlText = raw;
  }

  const parsed = parseYaml(yamlText);
  if (!parsed.ok) {
    const first = parsed.errors[0];
    return {
      findings: [
        makeFinding(
          "quarantine",
          "proposed",
          relFile,
          `Unparseable YAML: ${first?.message ?? "unknown error"}`,
          {
            ...(first?.line !== undefined ? { line: first.line } : {}),
            proposedFix: "Fix the YAML by hand; the file is skipped until then",
          },
        ),
      ],
    };
  }

  const findings = [
    ...validateData(parsed.data, schema, relFile, "on-disk"),
    ...validateBody(body, parsed.data, schema, relFile, "on-disk"),
  ];
  return { entity: { type, path, data: parsed.data, body }, findings };
}

/** Locates an entity file by identity within its scope directory. */
async function locateById(
  scope: ScopePaths,
  type: EntityType,
  id: string,
): Promise<string | undefined> {
  const dir = entityDir(scope, type);
  if (type === "article") {
    const target = resolve(dir, `${id}.md`);
    if (!isContained(dir, target)) {
      throw new Error(`Article slug escapes the articles directory: ${id}`);
    }
    return (await readFileOrUndefined(target)) !== undefined
      ? target
      : undefined;
  }
  const { files } = await walkFiles(dir);
  // Filename prefix match first — id is the identity, kebab-title a courtesy.
  const byName = files.find((f) => {
    const name = basename(f);
    return name === `${id}.md` || name.startsWith(`${id}-`);
  });
  if (byName !== undefined) return byName;
  // Fallback: a fully misnamed file still resolves via its frontmatter id.
  for (const file of files) {
    const raw = await readFileOrUndefined(file);
    if (raw === undefined) continue;
    const split = splitFrontmatter(raw);
    if (!split) continue;
    const parsed = parseYaml(split.yamlText);
    if (parsed.ok && parsed.data["id"] === id) return file;
  }
  return undefined;
}

/**
 * Reads one entity by reference. Fixed-path types (configs, curation) ignore
 * `id`. Returns no entity (and no findings) when the entity does not exist.
 */
export async function readEntity(ref: EntityRef): Promise<ReadResult> {
  const { scope, type, id } = ref;
  if (
    type === "workspace-config" ||
    type === "project-config" ||
    type === "curation"
  ) {
    return readEntityByPath(entityDir(scope, type), type, scope.workspaceRoot);
  }
  const path = await locateById(scope, type, id);
  if (path === undefined) return { findings: [] };
  return readEntityByPath(path, type, scope.workspaceRoot);
}

function matchesFilter(entity: Entity, filter?: EntityFilter): boolean {
  if (filter === undefined) return true;
  if (typeof filter === "function") return filter(entity);
  return Object.entries(filter).every(
    ([key, value]) => entity.data[key] === value,
  );
}

/**
 * Lists a scope's entities of one type. Malformed files contribute findings
 * and (when quarantined) are skipped — a broken hand edit never hides the
 * rest of the board.
 */
export async function listEntities(
  scope: ScopePaths,
  type: EntityType,
  filter?: EntityFilter,
): Promise<ListResult> {
  const dir = entityDir(scope, type);
  const { files, symlinks } = await walkFiles(dir);
  const entities: Entity[] = [];
  const findings: Finding[] = [];
  for (const link of symlinks) {
    findings.push(
      makeFinding(
        "symlink",
        "proposed",
        workspaceRelative(scope.workspaceRoot, link),
        "Symbolic link under a state path is skipped — links are never followed",
        { proposedFix: "Replace the symlink with a regular file" },
      ),
    );
  }
  for (const file of files) {
    const result = await readEntityByPath(file, type, scope.workspaceRoot);
    findings.push(...result.findings);
    if (result.entity && matchesFilter(result.entity, filter)) {
      entities.push(result.entity);
    }
  }
  return { entities, findings };
}

/** Computes the canonical target path for a write. */
function targetPathFor(input: WriteEntityInput): string {
  const { scope, type, data } = input;
  const dir = entityDir(scope, type);
  switch (type) {
    case "task":
    case "arc": {
      const id = typeof data["id"] === "string" ? data["id"] : "";
      const title = typeof data["title"] === "string" ? data["title"] : "";
      const kebab = kebabTitle(title);
      const target = join(
        dir,
        kebab.length > 0 ? `${id}-${kebab}.md` : `${id}.md`,
      );
      // The id is format-validated at the write boundary; this containment
      // check is defense in depth on the assembled path.
      if (!isContained(dir, target)) {
        throw new Error(`Entity id escapes its state directory: ${id}`);
      }
      return target;
    }
    case "article": {
      const slug = typeof data["slug"] === "string" ? data["slug"] : "";
      const target = resolve(dir, `${slug}.md`);
      if (!isContained(dir, target)) {
        throw new Error(`Article slug escapes the articles directory: ${slug}`);
      }
      return target;
    }
    case "doc": {
      if (input.path === undefined) {
        throw new Error("Doc writes require an explicit `path`");
      }
      // Containment inside the workspace root is enforced as a rejection
      // finding at the write boundary before this is ever used.
      return resolve(input.path);
    }
    default:
      return dir; // Fixed-path types: configs and curation.
  }
}

/** Serializes entity data canonically, preserving existing-file comments. */
function serializeData(
  data: Record<string, unknown>,
  keyOrder: readonly string[],
  existingYaml?: string,
): string {
  let doc: Document;
  const parsed =
    existingYaml !== undefined ? parseYaml(existingYaml) : undefined;
  if (parsed?.ok) {
    doc = parsed.doc;
    for (const key of Object.keys(parsed.data)) {
      if (!(key in data)) doc.delete(key);
    }
    for (const [key, value] of Object.entries(data)) {
      setPreservingComments(doc, key, value);
    }
  } else {
    doc = new Document(data);
  }
  canonicalizeDocument(doc, keyOrder);
  return stringifyCanonical(doc);
}

/**
 * Engine write path: validate at the boundary → canonical serialize → atomic
 * write (temp file + rename in the same directory — nothing half-written).
 * Invalid writes are REJECTED with the finding list. Defaults are resolved
 * and written into the file here (write time only). Non-rejecting findings
 * (e.g. V-7 unknown keys) are returned alongside success.
 *
 * Side effects (index update, board render) are not performed here: attach
 * them via `options.onWrite` (T-010/T-011 seam).
 */
export async function writeEntity(
  input: WriteEntityInput,
  options: WriteOptions = {},
): Promise<WriteResult> {
  const schema = ENTITY_SCHEMAS[input.type];
  const data = applyDefaults(input.data, schema);
  const body = input.body ?? "";

  // Identity-shape gate BEFORE any path is assembled from entity data: a
  // hostile id or an out-of-tree doc path must never shape a filesystem path.
  if (input.type === "task" || input.type === "arc") {
    const id = data["id"];
    if (typeof id !== "string" || !idPattern().test(id)) {
      return {
        ok: false,
        findings: [
          makeFinding(
            "V-8",
            "reject",
            "",
            `Invalid id \`${typeof id === "string" ? id : String(id)}\` on ${input.type}: ids must match the declared prefix table and slug alphabet`,
            { proposedFix: "Mint ids with mintId(); never hand-assemble them" },
          ),
        ],
      };
    }
  }
  if (input.type === "doc") {
    if (input.path === undefined) {
      throw new Error("Doc writes require an explicit `path`");
    }
    if (!isContained(input.scope.workspaceRoot, resolve(input.path))) {
      return {
        ok: false,
        findings: [
          makeFinding(
            "V-8",
            "reject",
            input.path,
            `Doc path \`${input.path}\` resolves outside the workspace root`,
            { proposedFix: "Write docs inside the workspace docs/ trees" },
          ),
        ],
      };
    }
  }

  const relFile = workspaceRelative(
    input.scope.workspaceRoot,
    targetPathFor({ ...input, data }),
  );
  const findings = [
    ...validateData(data, schema, relFile, "engine-write"),
    ...validateBody(body, data, schema, relFile, "engine-write"),
  ];
  if (findings.some((f) => f.mode === "reject")) {
    return { ok: false, findings };
  }

  const target = targetPathFor({ ...input, data });
  // Retitles rename the file: find any existing file for this identity.
  let previousPath: string | undefined;
  let existingYaml: string | undefined;
  const identity = schema.identity;
  if (identity !== null && typeof data[identity] === "string") {
    previousPath = await locateById(input.scope, input.type, data[identity]);
  } else {
    const existing = await readFileOrUndefined(target);
    if (existing !== undefined) previousPath = target;
  }
  if (previousPath !== undefined) {
    const raw = await readFileOrUndefined(previousPath);
    if (raw !== undefined) {
      existingYaml =
        schema.format === "markdown" ? splitFrontmatter(raw)?.yamlText : raw;
    }
  }

  const yamlText = serializeData(data, keyOrderOf(schema), existingYaml);
  const content =
    schema.format === "markdown" ? buildMarkdown(yamlText, body) : yamlText;

  await atomicWrite(input.scope.workspaceRoot, target, content);
  if (previousPath !== undefined && previousPath !== target) {
    await unlink(previousPath);
  }

  const entity: Entity = { type: input.type, path: target, data, body };
  await options.onWrite?.({
    path: target,
    ...(previousPath !== undefined && previousPath !== target
      ? { previousPath }
      : {}),
    entity,
    scope: input.scope,
  });
  return { ok: true, path: target, findings };
}

/**
 * Low-level repair-grade rewrite: read → mutate data → canonical serialize
 * (comments preserved) → atomic write. Skips boundary validation on purpose —
 * repairs must be able to touch files that are otherwise invalid. Optionally
 * renames the file (e.g. re-minted ids). Used by `repair()`, not by tools.
 */
export async function rewriteEntityFile(
  workspaceRoot: string,
  path: string,
  type: EntityType,
  mutate: (data: Record<string, unknown>) => Record<string, unknown>,
  renameTo?: string,
): Promise<void> {
  const schema = ENTITY_SCHEMAS[type];
  const raw = await readFile(path, "utf8");
  let yamlText: string;
  let body = "";
  if (schema.format === "markdown") {
    const split = splitFrontmatter(raw);
    if (split === undefined) {
      throw new Error(`Cannot rewrite ${path}: no frontmatter block`);
    }
    yamlText = split.yamlText;
    body = split.body;
  } else {
    yamlText = raw;
  }
  const parsed = parseYaml(yamlText);
  if (!parsed.ok) {
    throw new Error(`Cannot rewrite ${path}: unparseable YAML`);
  }
  const next = mutate(structuredClone(parsed.data));
  const serialized = serializeData(next, keyOrderOf(schema), yamlText);
  const content =
    schema.format === "markdown" ? buildMarkdown(serialized, body) : serialized;
  const target = renameTo ?? path;
  await atomicWrite(workspaceRoot, target, content);
  if (target !== path) await unlink(path);
}
