import { execFile } from "node:child_process";
import { mkdtemp, realpath, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, expect, it } from "vitest";

import { resolveRepoRoot } from "../../../src/git/index.js";

const execFileAsync = promisify(execFile);

describe("resolveRepoRoot (integration)", () => {
  let dir: string | undefined;

  afterEach(async () => {
    if (dir !== undefined) {
      await rm(dir, { recursive: true, force: true });
      dir = undefined;
    }
  });

  it("resolves the root of a freshly initialized repository", async () => {
    const tempDir = await mkdtemp(join(tmpdir(), "keel-repo-"));
    dir = tempDir;
    await execFileAsync("git", ["init"], { cwd: tempDir });

    const root = await resolveRepoRoot(tempDir);

    // realpath both sides: os.tmpdir() is a symlink on macOS (/tmp -> /private/tmp).
    expect(await realpath(root)).toBe(await realpath(tempDir));
  });
});
