/**
 * Declared-data registries for the state layer (Article 001, Engine/Data
 * Separation; Article 003, Registries Over Bespoke Code Paths). Everything in
 * this module is data the engine loads — schemas, id prefixes, validation rule
 * configuration — never logic. Extending the framework (new prefix, new rule,
 * lifted rule) is an edit here or an override parameter, not engine surgery.
 */

import { deepFreeze } from "../shared/index.js";

/** Field value types supported by entity schemas. */
export type FieldType =
  | "string"
  | "int"
  | "bool"
  | "date"
  | "enum"
  | "string-array"
  | "object"
  | "object-array"
  | "map";

/** One declared frontmatter/config field. */
export interface FieldSpec {
  readonly name: string;
  readonly type: FieldType;
  readonly required: boolean;
  /** Applied at mint/write time only — never silently defaulted at read. */
  readonly default?: unknown;
  readonly enumValues?: readonly string[];
  /** Optional value pattern (e.g. SemVer for doc `version`). */
  readonly pattern?: RegExp;
}

/** Body-section contract, e.g. article sections required at ratification. */
export interface BodyContract {
  readonly requiredSections: readonly string[];
  /** Contract applies only when this frontmatter field equals this value. */
  readonly when?: { readonly field: string; readonly equals: string };
}

/** Entity types known to the state layer. */
export type EntityType =
  | "task"
  | "arc"
  | "article"
  | "doc"
  | "workspace-config"
  | "project-config"
  | "curation";

/** A declared entity schema: field table plus body contract. */
export interface EntitySchema {
  readonly type: EntityType;
  readonly format: "markdown" | "yaml";
  /** Identity field name, or null when the file path is the identity. */
  readonly identity: string | null;
  readonly fields: readonly FieldSpec[];
  readonly body?: BodyContract;
}

const SEMVER = /^\d+\.\d+\.\d+$/;

/** Article categories (injection filters) shipped as declared data. */
export const ARTICLE_CATEGORIES: readonly string[] = deepFreeze([
  "design",
  "documentation",
  "collaboration",
  "testing",
  "security",
  "process",
  "general",
]);

/** Task statuses. */
export const TASK_STATUSES: readonly string[] = deepFreeze([
  "todo",
  "working",
  "awaiting-validation",
  "done",
  "frozen",
  "trashed",
]);

const taskSchema: EntitySchema = deepFreeze({
  type: "task",
  format: "markdown",
  identity: "id",
  fields: [
    { name: "id", type: "string", required: true },
    { name: "title", type: "string", required: true },
    {
      name: "status",
      type: "enum",
      required: true,
      default: "todo",
      enumValues: TASK_STATUSES,
    },
    {
      name: "category",
      type: "enum",
      required: true,
      enumValues: ["task", "bug", "security"],
    },
    {
      name: "priority",
      type: "enum",
      required: true,
      enumValues: ["P0", "P1", "P2", "P3"],
    },
    { name: "arc", type: "string", required: false },
    { name: "assignee", type: "string", required: false },
    { name: "depends_on", type: "string-array", required: false, default: [] },
    {
      name: "provenance",
      type: "object",
      required: false,
      default: { source: "user" },
    },
    { name: "created", type: "date", required: true },
    { name: "ext", type: "map", required: false },
  ],
});

const arcSchema: EntitySchema = deepFreeze({
  type: "arc",
  format: "markdown",
  identity: "id",
  fields: [
    { name: "id", type: "string", required: true },
    { name: "title", type: "string", required: true },
    {
      name: "status",
      type: "enum",
      required: true,
      default: "open",
      enumValues: ["open", "done"],
    },
    { name: "members", type: "string-array", required: true, default: [] },
    { name: "created", type: "date", required: true },
    { name: "ext", type: "map", required: false },
  ],
});

const articleSchema: EntitySchema = deepFreeze({
  type: "article",
  format: "markdown",
  identity: "slug",
  fields: [
    { name: "slug", type: "string", required: true },
    { name: "number", type: "int", required: true },
    { name: "title", type: "string", required: true },
    {
      name: "status",
      type: "enum",
      required: true,
      default: "proposed",
      enumValues: ["proposed", "ratified", "revoked"],
    },
    {
      name: "category",
      type: "enum",
      required: true,
      enumValues: ARTICLE_CATEGORIES,
    },
    { name: "triggers", type: "string-array", required: true },
    { name: "preferred_number", type: "int", required: false },
    { name: "provenance", type: "object", required: true },
    { name: "created", type: "date", required: true },
    { name: "amendments", type: "object-array", required: false, default: [] },
    { name: "ext", type: "map", required: false },
  ],
  body: {
    requiredSections: ["Context", "Rule", "Consequences", "Enforcement"],
    when: { field: "status", equals: "ratified" },
  },
});

const docSchema: EntitySchema = deepFreeze({
  type: "doc",
  format: "markdown",
  identity: null,
  fields: [
    { name: "version", type: "string", required: true, pattern: SEMVER },
    { name: "updated", type: "date", required: true },
    {
      name: "status",
      type: "enum",
      required: true,
      default: "Draft",
      enumValues: ["Draft", "Approved", "Deprecated"],
    },
    { name: "keywords", type: "string-array", required: false, default: [] },
    {
      name: "source_paths",
      type: "string-array",
      required: false,
      default: [],
    },
    { name: "load_at_start", type: "bool", required: false, default: false },
    { name: "ext", type: "map", required: false },
  ],
});

const workspaceConfigSchema: EntitySchema = deepFreeze({
  type: "workspace-config",
  format: "yaml",
  identity: null,
  fields: [
    { name: "schema_version", type: "int", required: true },
    { name: "name", type: "string", required: true },
    { name: "projects", type: "map", required: true, default: {} },
    { name: "retention", type: "map", required: false },
    { name: "scoring", type: "map", required: false },
    { name: "startup_budget", type: "int", required: false },
    { name: "delegation_threshold", type: "string", required: false },
    { name: "ext", type: "map", required: false },
  ],
});

const projectConfigSchema: EntitySchema = deepFreeze({
  type: "project-config",
  format: "yaml",
  identity: null,
  fields: [
    { name: "schema_version", type: "int", required: true },
    { name: "slug", type: "string", required: true },
    { name: "article_block", type: "int", required: true },
    // Reserved keys — sub-schemas owned by T-014 (features) and T-016 (pipeline).
    { name: "features", type: "map", required: false },
    { name: "pipeline", type: "object", required: false },
    { name: "ext", type: "map", required: false },
  ],
});

const curationSchema: EntitySchema = deepFreeze({
  type: "curation",
  format: "yaml",
  identity: null,
  fields: [
    { name: "modules", type: "map", required: true, default: {} },
    { name: "ext", type: "map", required: false },
  ],
});

/** The entity schema registry, keyed by entity type. */
export const ENTITY_SCHEMAS: Readonly<Record<EntityType, EntitySchema>> =
  deepFreeze({
    task: taskSchema,
    arc: arcSchema,
    article: articleSchema,
    doc: docSchema,
    "workspace-config": workspaceConfigSchema,
    "project-config": projectConfigSchema,
    curation: curationSchema,
  });

/** Canonical top-level key order for a schema (field declaration order). */
export function keyOrderOf(schema: EntitySchema): string[] {
  return schema.fields.map((f) => f.name);
}

/** One declared id prefix. */
export interface IdPrefixSpec {
  readonly prefix: string;
  readonly entityType: EntityType;
  /** Task category this prefix must agree with (V-6), if any. */
  readonly category: string | null;
}

/** The declared id-prefix table (registry-extensible per Article 003). */
export const ID_PREFIXES: readonly IdPrefixSpec[] = deepFreeze([
  { prefix: "T", entityType: "task", category: "task" },
  { prefix: "B", entityType: "task", category: "bug" },
  { prefix: "S", entityType: "task", category: "security" },
  { prefix: "A", entityType: "arc", category: null },
]);

/**
 * Lowercase Crockford-style base32 alphabet for id slugs: digits plus
 * consonant-safe letters, excluding `i l o u` (32 symbols).
 */
export const ID_SLUG_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz";

/** Length of the random slug portion of a minted id. */
export const ID_SLUG_LENGTH = 5;

/**
 * Regex an entity id must match, derived from the declared prefix table and
 * slug alphabet (never hardcoded): `^<prefix>-[alphabet]{length}$`. Used at
 * the write boundary so a hostile id can never shape a filesystem path.
 */
export function idPattern(
  prefixes: readonly IdPrefixSpec[] = ID_PREFIXES,
): RegExp {
  const alternatives = prefixes
    .map((p) => p.prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
  return new RegExp(
    `^(?:${alternatives})-[${ID_SLUG_ALPHABET}]{${ID_SLUG_LENGTH}}$`,
  );
}

/** Workspace-tier article number band (banded numbering standard). */
export const WORKSPACE_ARTICLE_BAND = { start: 1, end: 99 } as const;

/** Size of each project's article number block (base from config). */
export const PROJECT_ARTICLE_BAND_SIZE = 100;

/** How a validation finding is handled. */
export type FindingMode = "silent" | "proposed" | "reject";

/** Finding severity. */
export type FindingSeverity = "info" | "warning" | "error" | "critical";

/** One declared validation rule (the V-table as data). */
export interface ValidationRuleSpec {
  readonly rule: string;
  readonly id: string;
  /** Modes this rule can emit; each finding instance carries its actual mode. */
  readonly modes: readonly FindingMode[];
  readonly severity: FindingSeverity;
  /** Liftable rules can be removed by data change alone (G18 seam 1). */
  readonly liftable?: boolean;
  readonly description: string;
}

/**
 * The shipped validation rule configuration. Passing a filtered copy to
 * `validate` lifts a rule — a data change, not surgery.
 */
export const VALIDATION_RULES: readonly ValidationRuleSpec[] = deepFreeze([
  {
    rule: "quarantine",
    id: "unparseable-yaml",
    modes: ["proposed"],
    severity: "critical",
    description: "Unparseable YAML quarantines the file as a finding",
  },
  {
    rule: "symlink",
    id: "symlinked-state-file",
    modes: ["proposed"],
    severity: "warning",
    description: "Symbolic links under state paths are skipped, never followed",
  },
  {
    rule: "V-1",
    id: "duplicate-entity-id",
    modes: ["silent", "proposed"],
    severity: "error",
    description:
      "Same id in two files within one scope (re-mint is silent; ambiguous references become proposals)",
  },
  {
    rule: "V-2",
    id: "duplicate-article-number",
    modes: ["silent", "proposed"],
    severity: "error",
    description:
      "Duplicate article number in the same scope (proposed when the band is full)",
  },
  {
    rule: "V-3",
    id: "article-number-outside-band",
    modes: ["silent", "proposed"],
    severity: "error",
    description:
      "Article number outside the scope's band (proposed when the band is full)",
  },
  {
    rule: "V-4",
    id: "dangling-reference",
    modes: ["silent", "proposed"],
    severity: "warning",
    description: "Dangling depends_on / arc reference",
  },
  {
    rule: "V-5",
    id: "arc-membership-disagreement",
    modes: ["silent", "proposed"],
    severity: "warning",
    description: "Arc members and task arc back-reference disagree",
  },
  {
    rule: "V-6",
    id: "category-prefix-mismatch",
    modes: ["proposed"],
    severity: "error",
    description: "Task category does not agree with its id prefix",
  },
  {
    rule: "V-7",
    id: "unknown-frontmatter-key",
    modes: ["proposed"],
    severity: "warning",
    description: "Unknown bare frontmatter key (strict schema)",
  },
  {
    rule: "V-8",
    id: "missing-required-field",
    modes: ["reject", "proposed"],
    severity: "error",
    description: "Missing required field or body section",
  },
  {
    rule: "V-9",
    id: "invalid-enum-value",
    modes: ["reject", "proposed"],
    severity: "error",
    description: "Invalid enum value",
  },
  {
    rule: "V-10",
    id: "project-slug-mismatch",
    modes: ["proposed"],
    severity: "error",
    description: "Project config slug differs from its registry key",
  },
  {
    rule: "V-11",
    id: "workspace-internal-paths",
    modes: ["proposed"],
    severity: "error",
    liftable: true,
    description: "Declared project path escapes the workspace root",
  },
  {
    rule: "V-12",
    id: "non-canonical-serialization",
    modes: ["silent", "proposed"],
    severity: "info",
    description: "File is not in canonical YAML serialization",
  },
  {
    rule: "V-13",
    id: "tracked-derived-or-binary",
    modes: ["proposed"],
    severity: "critical",
    description: "Tracked derived/ephemera or binary file under state paths",
  },
]);

/** Looks up a validation rule spec by V-number within a rule config. */
export function ruleSpec(
  rule: string,
  rules: readonly ValidationRuleSpec[] = VALIDATION_RULES,
): ValidationRuleSpec | undefined {
  return rules.find((r) => r.rule === rule);
}

/** Looks up an id prefix spec within a prefix table. */
export function prefixSpec(
  prefix: string,
  prefixes: readonly IdPrefixSpec[] = ID_PREFIXES,
): IdPrefixSpec | undefined {
  return prefixes.find((p) => p.prefix === prefix);
}
