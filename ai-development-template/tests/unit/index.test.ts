import { describe, expect, it } from "vitest";

import { resolveRepoRoot, type ExecFileFn } from "../../src/index.js";

describe("public API surface", () => {
  it("exports resolveRepoRoot as a function", () => {
    expect(typeof resolveRepoRoot).toBe("function");
  });

  it("exports a usable ExecFileFn type", () => {
    // Type-level check: this assignment failing to compile fails `typecheck`.
    const fake: ExecFileFn = () => Promise.resolve({ stdout: "" });
    expect(typeof fake).toBe("function");
  });
});
