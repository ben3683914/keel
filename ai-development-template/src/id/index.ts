import { readdir } from "node:fs/promises";

import { entityDir, type ScopePaths } from "../layout/index.js";
import {
  ID_PREFIXES,
  ID_SLUG_ALPHABET,
  ID_SLUG_LENGTH,
  prefixSpec,
  type IdPrefixSpec,
} from "../registry/index.js";

/**
 * Injectable randomness seam: returns a float in [0, 1). Minting is the one
 * sanctioned randomness source (Article 002 bars randomness from operation
 * outcomes; minting is a creation event) — tests inject a deterministic fn.
 */
export type RandomFn = () => number;

/** Injectable clock seam: `created` is stamped once at mint, never updated. */
export type ClockFn = () => Date;

/** Options for `mintId`. */
export interface MintOptions {
  rng?: RandomFn;
  clock?: ClockFn;
  /** Prefix table override (registry-extensible, Article 003). */
  prefixes?: readonly IdPrefixSpec[];
  /** Collision-retry cap before giving up with an error. */
  maxAttempts?: number;
}

/** A freshly minted identity. */
export interface MintedId {
  id: string;
  /** Mint date, `YYYY-MM-DD` (UTC). */
  created: string;
}

/** Formats a Date as the canonical `YYYY-MM-DD` (UTC) mint date. */
export function formatMintDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Draws one random slug from the declared alphabet. */
export function drawSlug(rng: RandomFn): string {
  let slug = "";
  for (let i = 0; i < ID_SLUG_LENGTH; i++) {
    const idx = Math.min(
      Math.floor(rng() * ID_SLUG_ALPHABET.length),
      ID_SLUG_ALPHABET.length - 1,
    );
    slug += ID_SLUG_ALPHABET[idx];
  }
  return slug;
}

/** Lists the entity ids already present in a directory's filenames. */
async function existingIds(dir: string): Promise<Set<string>> {
  let names: string[];
  try {
    names = await readdir(dir);
  } catch {
    return new Set(); // Directory absent — no entities, no collisions.
  }
  const ids = new Set<string>();
  for (const name of names) {
    const m = /^([A-Z]+-[0-9a-z]+)[-.]/.exec(name);
    if (m?.[1]) ids.add(m[1]);
  }
  return ids;
}

/**
 * Mints a new collision-checked id for a scope: draw a random slug, check
 * against the scope's entity files, retry on collision. Also stamps the
 * `created` date via the injectable clock.
 */
export async function mintId(
  prefix: string,
  scope: ScopePaths,
  options: MintOptions = {},
): Promise<MintedId> {
  const prefixes = options.prefixes ?? ID_PREFIXES;
  const spec = prefixSpec(prefix, prefixes);
  if (!spec) {
    const known = prefixes.map((p) => p.prefix).join(", ");
    throw new Error(`Unknown id prefix \`${prefix}\` (declared: ${known})`);
  }
  const rng = options.rng ?? Math.random;
  const clock = options.clock ?? (() => new Date());
  const maxAttempts = options.maxAttempts ?? 50;
  const taken = await existingIds(entityDir(scope, spec.entityType));

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const id = `${prefix}-${drawSlug(rng)}`;
    if (!taken.has(id)) {
      return { id, created: formatMintDate(clock()) };
    }
  }
  throw new Error(
    `Could not mint a unique \`${prefix}-\` id after ${maxAttempts} attempts`,
  );
}
