import { execFile } from "node:child_process";
import { promisify } from "node:util";

/** Minimal exec seam so callers/tests can substitute the process spawn. */
export type ExecFileFn = (
  file: string,
  args: readonly string[],
  options: { cwd: string },
) => Promise<{ stdout: string }>;

const defaultExecFile: ExecFileFn = promisify(execFile);

/**
 * Resolves the absolute root of the git repository containing `startDir`.
 * The repo is always an explicit parameter (G18 seam 3) — the engine never
 * assumes `process.cwd()` is the repo.
 */
export async function resolveRepoRoot(
  startDir: string,
  exec: ExecFileFn = defaultExecFile,
): Promise<string> {
  try {
    const { stdout } = await exec("git", ["rev-parse", "--show-toplevel"], {
      cwd: startDir,
    });
    return stdout.trim();
  } catch (error) {
    throw new Error(`Not inside a git repository: ${startDir}`, {
      cause: error,
    });
  }
}
