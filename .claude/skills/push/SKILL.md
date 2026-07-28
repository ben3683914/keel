---
name: push
description: Push to remote repository with user confirmation
disable-model-invocation: true
argument-hint: "[remote] [branch]"
---

Safe push workflow. Direct `git push` is denied by permissions — this skill is the only way to push.

## Steps

1. Run `git status` and `git log --oneline @{u}..HEAD` to show what will be pushed (unpushed commits)
   - If no upstream is set, show `git log --oneline -5` instead and note this will set upstream
2. Show the user: remote, branch, number of commits, and commit summaries
3. Ask for confirmation via AskUserQuestion: "Push N commits to remote/branch?"
4. If confirmed, run: `.claude/venv/bin/python .claude/scripts/shared/git_push.py` with appropriate args
5. Report the result

## Arguments

If `$ARGUMENTS` is provided, pass as remote and branch (e.g., `/push origin main`).
Otherwise default to the current branch's upstream.

## Tags

The push always uses `--follow-tags`, so **annotated** tags pointing at commits being
pushed (e.g. release tags like `v1.6.0`) ride along automatically — no separate step.
To also push tags that are NOT reachable from the branch (e.g. backfilling older release
tags, or when the branch is already up to date), pass `--tags`, which pushes all local tags.

## Script

The push script is at `.claude/scripts/shared/git_push.py`. Always invoke it with the
venv interpreter — bare `python` does not exist on macOS:
```
.claude/venv/bin/python .claude/scripts/shared/git_push.py [remote] [branch] [--set-upstream] [--tags]
```
