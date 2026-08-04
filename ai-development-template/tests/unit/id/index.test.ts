import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { drawSlug, formatMintDate, mintId } from "../../../src/id/index.js";
import { workspaceScope } from "../../../src/layout/index.js";
import { ID_SLUG_ALPHABET } from "../../../src/registry/index.js";

/** Deterministic rng cycling through provided values. */
function seededRng(values: number[]): () => number {
  let i = 0;
  return () => values[i++ % values.length] ?? 0;
}

const FIXED_CLOCK = (): Date => new Date("2026-07-29T12:00:00Z");

describe("drawSlug", () => {
  it("draws 5 chars from the declared alphabet, deterministically", () => {
    const slug = drawSlug(seededRng([0, 0.5, 0.99, 0.25, 0.75]));
    expect(slug).toHaveLength(5);
    expect(slug).toBe(
      [
        ID_SLUG_ALPHABET[0],
        ID_SLUG_ALPHABET[16],
        ID_SLUG_ALPHABET[31],
        ID_SLUG_ALPHABET[8],
        ID_SLUG_ALPHABET[24],
      ].join(""),
    );
  });

  it("clamps an rng returning exactly 1 to the last symbol", () => {
    expect(drawSlug(() => 1)).toBe(ID_SLUG_ALPHABET[31]?.repeat(5));
  });
});

describe("formatMintDate", () => {
  it("formats as UTC YYYY-MM-DD", () => {
    expect(formatMintDate(new Date("2026-07-29T23:59:00Z"))).toBe("2026-07-29");
  });
});

describe("mintId", () => {
  let dir: string | undefined;

  afterEach(async () => {
    if (dir !== undefined) {
      await rm(dir, { recursive: true, force: true });
      dir = undefined;
    }
  });

  async function tempScope(): Promise<ReturnType<typeof workspaceScope>> {
    dir = await mkdtemp(join(tmpdir(), "keel-id-"));
    return workspaceScope(dir);
  }

  it("mints prefix-slug ids and stamps created via the clock seam", async () => {
    const scope = await tempScope();
    const minted = await mintId("T", scope, {
      rng: seededRng([0.1]),
      clock: FIXED_CLOCK,
    });
    expect(minted.id).toMatch(/^T-[0-9a-z]{5}$/);
    expect(minted.created).toBe("2026-07-29");
  });

  it("collision-checks against the scope's entity files and retries", async () => {
    const scope = await tempScope();
    await mkdir(scope.tasksDir, { recursive: true });
    const colliding = drawSlug(seededRng([0.1]));
    await writeFile(
      join(scope.tasksDir, `T-${colliding}-existing.md`),
      "---\nid: T-" + colliding + "\n---\n",
    );
    // First draw collides, second draw (0.9-based) succeeds.
    const rngValues = [
      ...Array<number>(5).fill(0.1),
      ...Array<number>(5).fill(0.9),
    ];
    const minted = await mintId("T", scope, {
      rng: seededRng(rngValues),
      clock: FIXED_CLOCK,
    });
    expect(minted.id).not.toBe(`T-${colliding}`);
  });

  it("arc minting checks the arcs directory, not tasks", async () => {
    const scope = await tempScope();
    const minted = await mintId("A", scope, {
      rng: seededRng([0.5]),
      clock: FIXED_CLOCK,
    });
    expect(minted.id).toMatch(/^A-/);
  });

  it("throws on an undeclared prefix, listing declared ones", async () => {
    const scope = await tempScope();
    await expect(mintId("X", scope)).rejects.toThrow(/T, B, S, A/);
  });

  it("honors a registry-extended prefix table (Article 003)", async () => {
    const scope = await tempScope();
    const minted = await mintId("E", scope, {
      rng: seededRng([0.2]),
      clock: FIXED_CLOCK,
      prefixes: [{ prefix: "E", entityType: "task", category: "task" }],
    });
    expect(minted.id).toMatch(/^E-/);
  });

  it("gives up deterministically after maxAttempts collisions", async () => {
    const scope = await tempScope();
    await mkdir(scope.tasksDir, { recursive: true });
    const slug = drawSlug(() => 0.3);
    await writeFile(join(scope.tasksDir, `T-${slug}-taken.md`), "x");
    await expect(
      mintId("T", scope, { rng: () => 0.3, maxAttempts: 3 }),
    ).rejects.toThrow(/after 3 attempts/);
  });
});
