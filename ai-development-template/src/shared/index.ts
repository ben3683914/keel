import { randomBytes } from "node:crypto";
import { mkdir, rename, rm, writeFile } from "node:fs/promises";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
} from "node:path";

/**
 * Recursively freezes a value and returns it with its static type intact.
 *
 * `readonly` is erased at compile time, so a shipped table declared only with
 * `readonly` stays mutable at runtime — and the shipped tables are security
 * controls (the validation rule table, the id-prefix table, the state-kind
 * classification table). Freezing them at declaration makes tampering fail
 * instead of silently disabling a rule. Override seams are unaffected:
 * callers still pass their own arrays, which are never frozen by this.
 */
export function deepFreeze<T>(value: T): T {
  if (typeof value !== "object" || value === null) return value;
  if (Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const key of Object.getOwnPropertyNames(value)) {
    deepFreeze((value as Record<string, unknown>)[key]);
  }
  return value;
}

/** Narrows to a plain string-keyed record (not null, not an array). */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Narrows to an array of strings. */
export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

/**
 * True when `target` resolves strictly inside `rootDir`. Uses `relative()`
 * (no `..` prefix, not absolute, not the root itself) so it is correct on
 * Windows as well as POSIX.
 */
export function isContained(rootDir: string, target: string): boolean {
  const rel = relative(resolve(rootDir), resolve(target));
  return rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
}

/**
 * Asserts `target` resolves inside `rootDir`. Every write this library
 * performs goes through this check (via `atomicWrite`) — the single
 * chokepoint against path-traversal writes escaping the workspace.
 */
export function assertContained(rootDir: string, target: string): void {
  if (!isContained(rootDir, target)) {
    throw new Error(
      `Refusing to write outside the workspace root: ${target} is not inside ${rootDir}`,
    );
  }
}

/**
 * Atomic, contained write: temp file + rename in the same directory, so a
 * crash never leaves a half-written entity (Article 002). Hardened:
 * - `target` must resolve inside the explicitly passed `rootDir`;
 * - the temp name carries a random suffix and is created with `wx` (fails on
 *   any pre-existing path, including a planted symlink; creation-time
 *   randomness is not an operation outcome);
 * - explicit `mode: 0o644` for the final content file;
 * - the temp file is unlinked on every failure path.
 */
export async function atomicWrite(
  rootDir: string,
  target: string,
  content: string,
): Promise<void> {
  assertContained(rootDir, target);
  const dir = dirname(target);
  await mkdir(dir, { recursive: true });
  const temp = join(
    dir,
    `.${basename(target)}.${randomBytes(6).toString("hex")}.tmp`,
  );
  try {
    await writeFile(temp, content, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o644,
    });
    await rename(temp, target);
  } catch (error) {
    await rm(temp, { force: true });
    throw error;
  }
}
