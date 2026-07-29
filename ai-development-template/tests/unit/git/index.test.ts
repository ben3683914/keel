import { describe, expect, it } from "vitest";

import { resolveRepoRoot, type ExecFileFn } from "../../../src/git/index.js";

describe("resolveRepoRoot", () => {
  it("rejects with a clear error when git reports no repository", async () => {
    const failingExec: ExecFileFn = () =>
      Promise.reject(
        new Error(
          "fatal: not a git repository (or any of the parent directories): .git",
        ),
      );

    await expect(resolveRepoRoot("/some/dir", failingExec)).rejects.toThrow(
      /not inside a git repository: \/some\/dir/i,
    );
  });

  it("returns the trimmed repo root and passes startDir as cwd", async () => {
    const calls: { file: string; args: readonly string[]; cwd: string }[] = [];
    const fakeExec: ExecFileFn = (file, args, options) => {
      calls.push({ file, args, cwd: options.cwd });
      return Promise.resolve({ stdout: "/repo/root\n" });
    };

    await expect(resolveRepoRoot("/repo/root/sub", fakeExec)).resolves.toBe(
      "/repo/root",
    );
    expect(calls).toEqual([
      {
        file: "git",
        args: ["rev-parse", "--show-toplevel"],
        cwd: "/repo/root/sub",
      },
    ]);
  });
});
