#!/usr/bin/env python3
"""Git push wrapper for the /push skill.

Called by Claude via the push skill after user confirmation.
Direct git push is denied by permissions — this script is the approved path.

By default this pushes the branch with --follow-tags, so annotated tags that
point at commits being pushed (e.g. release tags like v1.6.0) ride along
automatically. Pass --tags to additionally push ALL local tags.

Pass --force to force-push (uses --force-with-lease, which overwrites the remote
branch but refuses if it moved since our last fetch).

Usage:
    python git_push.py [remote] [branch] [--set-upstream] [--tags] [--force]
"""

import json
import subprocess
import sys


def run_git(*args):
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def main():
    remote = None
    branch = None
    set_upstream = False
    push_all_tags = False
    force = False

    args = sys.argv[1:]
    for arg in args:
        if arg == "--set-upstream":
            set_upstream = True
        elif arg == "--tags":
            push_all_tags = True
        elif arg == "--force":
            force = True
        elif remote is None:
            remote = arg
        elif branch is None:
            branch = arg

    # Default to current branch
    if not branch:
        code, branch_name, _ = run_git("rev-parse", "--abbrev-ref", "HEAD")
        if code != 0:
            print(json.dumps({"error": "Could not determine current branch"}))
            sys.exit(1)
        branch = branch_name

    # Default remote
    if not remote:
        remote = "origin"

    # Build push command. --follow-tags carries annotated tags (release tags)
    # that point at commits being pushed, without dragging up unrelated tags.
    cmd = ["push", "--follow-tags"]
    if force:
        cmd.append("--force-with-lease")
    if set_upstream:
        cmd.append("-u")
    cmd.extend([remote, branch])

    code, stdout, stderr = run_git(*cmd)

    output = {
        "success": code == 0,
        "remote": remote,
        "branch": branch,
        "output": stdout or stderr,
    }

    # Optionally push ALL tags (e.g. backfilling release tags not reachable
    # from the pushed branch, or pushing tags when the branch is already up to date).
    if push_all_tags:
        t_code, t_stdout, t_stderr = run_git("push", remote, "--tags")
        output["tags_pushed"] = t_code == 0
        output["tags_output"] = t_stdout or t_stderr
        if t_code != 0:
            output["success"] = False

    print(json.dumps(output, indent=2))
    sys.exit(0 if output["success"] else 1)


if __name__ == "__main__":
    main()
