import { describe, expect, it } from "vitest";

import {
  deletedPathsMatching,
  lsTrackedFiles,
  resolveRepoRoot,
  type ExecFileFn,
} from "../../../src/git/index.js";

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

describe("lsTrackedFiles", () => {
  it("runs NUL-separated with quoting disabled and an explicit maxBuffer", async () => {
    const fakeExec: ExecFileFn = (_file, args, options) => {
      expect(args).toEqual(["-c", "core.quotePath=false", "ls-files", "-z"]);
      expect(options.cwd).toBe("/repo");
      expect(options.maxBuffer).toBe(64 * 1024 * 1024);
      // NUL separation keeps newline-containing and non-ASCII names intact.
      return Promise.resolve({
        stdout: "a.md\0state/tasks/T-1.md\0.keel/we\u00efrd\nname.json\0",
      });
    };
    await expect(lsTrackedFiles("/repo", fakeExec)).resolves.toEqual([
      "a.md",
      "state/tasks/T-1.md",
      ".keel/we\u00efrd\nname.json",
    ]);
  });

  it("returns an empty list outside a git repository (benign)", async () => {
    const failing: ExecFileFn = () =>
      Promise.reject(new Error("fatal: not a git repository"));
    await expect(lsTrackedFiles("/nope", failing)).resolves.toEqual([]);
  });

  it("surfaces any other failure instead of silently disabling V-13", async () => {
    const failing: ExecFileFn = () =>
      Promise.reject(new Error("stdout maxBuffer length exceeded"));
    await expect(lsTrackedFiles("/repo", failing)).rejects.toThrow(
      /git ls-files failed/,
    );
  });
});

describe("deletedPathsMatching", () => {
  it("keeps a deleted filename containing a newline as one entry", async () => {
    // Splitting history output on "\n" mangles such a path, and V-4's
    // substring match could then resolve against a mangled entry — silently
    // annotating a dangling ref as resolved-by-archive instead of proposing
    // it. `-z` returns paths verbatim (verified against real git).
    const fakeExec: ExecFileFn = (_file, args) => {
      expect(args).toContain("-z");
      return Promise.resolve({
        stdout:
          "state/tasks/T-aaa11-normal.md\0state/tasks/T-bbb22-we\nird.md\0",
      });
    };
    await expect(deletedPathsMatching("/repo", "", fakeExec)).resolves.toEqual([
      "state/tasks/T-aaa11-normal.md",
      "state/tasks/T-bbb22-we\nird.md",
    ]);
  });

  it("filters deleted-in-history paths by needle, deduplicated", async () => {
    const fakeExec: ExecFileFn = (_file, args, options) => {
      expect(args).toEqual([
        "-c",
        "core.quotePath=false",
        "log",
        "--all",
        "--diff-filter=D",
        "--name-only",
        "-z",
        "--pretty=format:",
      ]);
      expect(options.cwd).toBe("/repo");
      return Promise.resolve({
        stdout:
          "state/tasks/T-abc12-old.md\0\0other.md\0state/tasks/T-abc12-old.md\0",
      });
    };
    await expect(
      deletedPathsMatching("/repo", "T-abc12", fakeExec),
    ).resolves.toEqual(["state/tasks/T-abc12-old.md"]);
  });

  it("returns an empty list outside a git repository or with no commits", async () => {
    const noRepo: ExecFileFn = () =>
      Promise.reject(new Error("fatal: not a git repository"));
    await expect(deletedPathsMatching("/nope", "T-x", noRepo)).resolves.toEqual(
      [],
    );
    const noCommits: ExecFileFn = () =>
      Promise.reject(
        new Error(
          "fatal: your current branch 'main' does not have any commits yet",
        ),
      );
    await expect(
      deletedPathsMatching("/repo", "T-x", noCommits),
    ).resolves.toEqual([]);
  });

  it("surfaces other failures as errors", async () => {
    const failing: ExecFileFn = () =>
      Promise.reject(new Error("stdout maxBuffer length exceeded"));
    await expect(deletedPathsMatching("/repo", "T-x", failing)).rejects.toThrow(
      /git history lookup failed/,
    );
  });
});
