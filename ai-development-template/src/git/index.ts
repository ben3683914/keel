import { execFile } from "node:child_process";
import { promisify } from "node:util";

/**
 * Minimal exec seam so callers/tests can substitute the process spawn.
 * `maxBuffer` is passed explicitly by the helpers — large repos produce
 * multi-megabyte listings, and a silent overflow would disable V-13.
 */
export type ExecFileFn = (
  file: string,
  args: readonly string[],
  options: { cwd: string; maxBuffer?: number },
) => Promise<{ stdout: string }>;

const defaultExecFile: ExecFileFn = promisify(execFile);

/** Generous output cap: ~64 MiB covers hundreds of thousands of paths. */
const MAX_GIT_BUFFER = 64 * 1024 * 1024;

/** True when the failure means "not a git repository" (a benign state). */
function isNotARepo(error: unknown): boolean {
  const parts: string[] = [];
  if (error instanceof Error) parts.push(error.message);
  const stderr = (error as { stderr?: unknown }).stderr;
  if (typeof stderr === "string") parts.push(stderr);
  return /not a git repository/i.test(parts.join(" "));
}

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

/**
 * Lists the repo-relative paths tracked by git (used by V-13's scan for
 * tracked derived/ephemera and binary state files). NUL-separated with
 * quoting disabled, so non-ASCII and newline-containing filenames come back
 * verbatim instead of C-quoted (which would bypass prefix classification).
 *
 * Returns an empty list when `repoRoot` is not a git repository — a benign
 * state the validator adapts to. Any other failure (e.g. output overflow)
 * throws, so callers surface it as a finding instead of silently skipping.
 */
export async function lsTrackedFiles(
  repoRoot: string,
  exec: ExecFileFn = defaultExecFile,
): Promise<string[]> {
  try {
    const { stdout } = await exec(
      "git",
      ["-c", "core.quotePath=false", "ls-files", "-z"],
      { cwd: repoRoot, maxBuffer: MAX_GIT_BUFFER },
    );
    return stdout.split("\0").filter((line) => line.length > 0);
  } catch (error) {
    if (isNotARepo(error)) return [];
    throw new Error(`git ls-files failed in ${repoRoot}`, { cause: error });
  }
}

/**
 * Lists repo-relative paths of files deleted at any point in history whose
 * path contains `needle` (used by V-4 to detect pruned-to-archive entities;
 * callers pass `""` to fetch the full deleted set once and filter in JS).
 * Returns an empty list outside a git repository or with no history; other
 * failures throw so callers can surface them as findings.
 */
export async function deletedPathsMatching(
  repoRoot: string,
  needle: string,
  exec: ExecFileFn = defaultExecFile,
): Promise<string[]> {
  try {
    const { stdout } = await exec(
      "git",
      [
        "-c",
        "core.quotePath=false",
        "log",
        "--all",
        "--diff-filter=D",
        "--name-only",
        "-z",
        "--pretty=format:",
      ],
      { cwd: repoRoot, maxBuffer: MAX_GIT_BUFFER },
    );
    // NUL-separated: a deleted filename containing a newline must stay one
    // entry, or V-4's substring match could hit a fragment and wrongly
    // annotate a dangling ref as resolved-by-archive.
    return [
      ...new Set(
        stdout
          .split("\0")
          .filter((line) => line.length > 0 && line.includes(needle)),
      ),
    ];
  } catch (error) {
    // A repo with no commits yet has no history — benign, like not-a-repo.
    const message = error instanceof Error ? error.message : "";
    if (isNotARepo(error) || /does not have any commits/i.test(message)) {
      return [];
    }
    throw new Error(`git history lookup failed in ${repoRoot}`, {
      cause: error,
    });
  }
}
