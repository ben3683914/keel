import {
  ruleSpec,
  type EntitySchema,
  type FieldSpec,
  type FindingMode,
  type FindingSeverity,
} from "../registry/index.js";
import { isRecord, isStringArray } from "../shared/index.js";
import { bodySectionHeadings } from "../yaml/index.js";

/**
 * A structured validation finding — everything the findings→task pipeline
 * needs: rule id, mode/severity, file, line where known, message, proposed
 * fix, plus an internal repair payload consumed by `repair()`.
 */
export interface Finding {
  /** V-number from the declared rule table, e.g. "V-8". */
  rule: string;
  /** Stable rule id, e.g. "missing-required-field". */
  ruleId: string;
  /** How this instance is handled: silent repair, proposal, or rejection. */
  mode: FindingMode;
  severity: FindingSeverity;
  /** Workspace-relative file path ("" when not file-specific). */
  file: string;
  /** 1-based line number where known. */
  line?: number;
  message: string;
  proposedFix?: string;
  /** Internal payload enabling `repair()` to apply the fix. */
  repair?: unknown;
}

/** Builds a finding, resolving ruleId/severity from the declared rule table. */
export function makeFinding(
  rule: string,
  mode: FindingMode,
  file: string,
  message: string,
  extra?: Partial<Pick<Finding, "line" | "proposedFix" | "repair">>,
): Finding {
  const spec = ruleSpec(rule);
  return {
    rule,
    ruleId: spec?.id ?? rule,
    mode,
    severity: spec?.severity ?? "error",
    file,
    message,
    ...(extra?.line !== undefined ? { line: extra.line } : {}),
    ...(extra?.proposedFix !== undefined
      ? { proposedFix: extra.proposedFix }
      : {}),
    ...(extra?.repair !== undefined ? { repair: extra.repair } : {}),
  };
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** Checks a single value against its field spec; returns a problem or null. */
function checkFieldType(field: FieldSpec, value: unknown): string | null {
  switch (field.type) {
    case "string":
      if (typeof value !== "string") return "must be a string";
      if (field.pattern && !field.pattern.test(value))
        return `must match ${String(field.pattern)}`;
      return null;
    case "int":
      return Number.isInteger(value) ? null : "must be an integer";
    case "bool":
      return typeof value === "boolean" ? null : "must be a boolean";
    case "date":
      return typeof value === "string" && DATE_PATTERN.test(value)
        ? null
        : "must be a YYYY-MM-DD date";
    case "enum":
      // Enum membership is V-9's concern, handled separately.
      return typeof value === "string" ? null : "must be a string";
    case "string-array":
      return isStringArray(value) ? null : "must be a list of strings";
    case "object":
      return isRecord(value) ? null : "must be a mapping";
    case "object-array":
      return Array.isArray(value) && value.every(isRecord)
        ? null
        : "must be a list of mappings";
    case "map":
      return isRecord(value) ? null : "must be a mapping";
  }
}

/**
 * Returns a copy of `data` with schema defaults filled in for absent fields.
 * Defaults apply at mint/write time ONLY — reads never call this; a required
 * field missing on disk is a V-8 finding, never silently defaulted.
 */
export function applyDefaults(
  data: Record<string, unknown>,
  schema: EntitySchema,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...data };
  for (const field of schema.fields) {
    if (out[field.name] === undefined && field.default !== undefined) {
      out[field.name] = structuredClone(field.default);
    }
  }
  return out;
}

/** Options for `validateData`. */
export interface ValidateDataOptions {
  /**
   * Declared schemas for named `ext:` blocks (feature-registry seam, T-014).
   * `ext:` content without a declared schema is always preserved untouched.
   */
  extSchemas?: Readonly<Record<string, readonly FieldSpec[]>>;
}

/**
 * Validates frontmatter/config data against a declared schema. `boundary`
 * selects the mode findings carry: engine writes are rejected ("reject"),
 * on-disk files become proposed findings — adapt, don't enforce.
 */
export function validateData(
  data: Record<string, unknown>,
  schema: EntitySchema,
  file: string,
  boundary: "engine-write" | "on-disk",
  options: ValidateDataOptions = {},
): Finding[] {
  const hardMode: FindingMode =
    boundary === "engine-write" ? "reject" : "proposed";
  const findings: Finding[] = [];
  const known = new Set(schema.fields.map((f) => f.name));

  for (const key of Object.keys(data)) {
    if (!known.has(key)) {
      findings.push(
        makeFinding(
          "V-7",
          "proposed",
          file,
          `Unknown key \`${key}\` in ${schema.type} frontmatter`,
          {
            proposedFix: `Fix the likely typo, or move it under \`ext:\` if intentional`,
          },
        ),
      );
    }
  }

  for (const field of schema.fields) {
    const value = data[field.name];
    if (value === undefined || value === null) {
      if (field.required) {
        findings.push(
          makeFinding(
            "V-8",
            hardMode,
            file,
            `Missing required field \`${field.name}\` on ${schema.type}`,
            {
              proposedFix:
                field.default !== undefined
                  ? `Add \`${field.name}: ${JSON.stringify(field.default)}\``
                  : `Add the required \`${field.name}\` field`,
            },
          ),
        );
      }
      continue;
    }
    const problem = checkFieldType(field, value);
    if (problem !== null) {
      findings.push(
        makeFinding(
          "V-8",
          hardMode,
          file,
          `Field \`${field.name}\` on ${schema.type} ${problem}`,
        ),
      );
      continue;
    }
    if (
      field.type === "enum" &&
      field.enumValues &&
      !field.enumValues.includes(value as string)
    ) {
      findings.push(
        makeFinding(
          "V-9",
          hardMode,
          file,
          `Invalid \`${field.name}\` value \`${value as string}\` on ${schema.type}`,
          { proposedFix: `Use one of: ${field.enumValues.join(", ")}` },
        ),
      );
    }
  }

  findings.push(...validateExt(data, file, hardMode, options));
  return findings;
}

/** Validates declared `ext:` block schemas; undeclared blocks are untouched. */
function validateExt(
  data: Record<string, unknown>,
  file: string,
  hardMode: FindingMode,
  options: ValidateDataOptions,
): Finding[] {
  const findings: Finding[] = [];
  const ext = data["ext"];
  if (!isRecord(ext) || options.extSchemas === undefined) return findings;
  for (const [name, fields] of Object.entries(options.extSchemas)) {
    const block = ext[name];
    if (block === undefined) continue;
    if (!isRecord(block)) {
      findings.push(
        makeFinding("V-8", hardMode, file, `\`ext.${name}\` must be a mapping`),
      );
      continue;
    }
    for (const field of fields) {
      const value = block[field.name];
      if (value === undefined) {
        if (field.required) {
          findings.push(
            makeFinding(
              "V-8",
              hardMode,
              file,
              `Missing required field \`ext.${name}.${field.name}\``,
            ),
          );
        }
        continue;
      }
      const problem = checkFieldType(field, value);
      if (problem !== null) {
        findings.push(
          makeFinding(
            "V-8",
            hardMode,
            file,
            `Field \`ext.${name}.${field.name}\` ${problem}`,
          ),
        );
      }
    }
  }
  return findings;
}

/**
 * Validates a markdown body against the schema's body-section contract
 * (e.g. article `## Context`/`## Rule`/`## Consequences`/`## Enforcement`
 * required at ratification).
 */
export function validateBody(
  body: string,
  data: Record<string, unknown>,
  schema: EntitySchema,
  file: string,
  boundary: "engine-write" | "on-disk",
): Finding[] {
  const contract = schema.body;
  if (!contract) return [];
  if (contract.when && data[contract.when.field] !== contract.when.equals) {
    return [];
  }
  const mode: FindingMode = boundary === "engine-write" ? "reject" : "proposed";
  const present = new Set(bodySectionHeadings(body));
  const findings: Finding[] = [];
  for (const section of contract.requiredSections) {
    if (!present.has(section)) {
      findings.push(
        makeFinding(
          "V-8",
          mode,
          file,
          `Missing required body section \`## ${section}\` on ${schema.type}`,
          { proposedFix: `Add a \`## ${section}\` section to the body` },
        ),
      );
    }
  }
  return findings;
}
