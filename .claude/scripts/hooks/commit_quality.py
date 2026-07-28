#!/usr/bin/env python3
"""PreToolUse hook: basic commit quality checks that apply to ALL project modes.

Fires on Bash tool calls. Checks if the command is a git commit.
Enforces:
1. Build verification (from project-config.json build_command)
2. Commit message conventions (conventional commits)
3. No Claude/Anthropic branding in commit message

These checks run in every mode (scratchpad, single-purpose, multi-purpose).
Review and task enforcement lives in commit_gate.py (enforcement modes only).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_project_root  # noqa: E402


# Allowed conventional commit types
COMMIT_TYPES = {"feat", "fix", "refactor", "docs", "test", "chore", "style", "perf"}

# Branding patterns to reject
BRANDING_PATTERNS = [
    re.compile(r"Co-Authored-By", re.IGNORECASE),
    re.compile(r"\bClaude\b"),
    re.compile(r"\bAnthropic\b"),
    re.compile(r"noreply@anthropic\.com", re.IGNORECASE),
]


def load_project_config(cwd):
    config_path = Path(cwd) / ".claude" / "project-config.json"
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def extract_commit_message(command):
    if re.search(r"-m\s+\"\$\(cat\s+<<", command):
        lines = command.split("\n")
        for line in lines[1:]:
            stripped = line.strip()
            if stripped and stripped not in ("EOF", ")\"", ")") and not stripped.startswith("EOF"):
                return stripped
        return None
    match = re.search(r"""-m\s+["']([^"']+)["']""", command)
    if match:
        return match.group(1)
    return None


def extract_full_commit_message(command):
    if re.search(r"-m\s+\"\$\(cat\s+<<", command):
        lines = command.split("\n")
        msg_lines = []
        in_msg = False
        for line in lines:
            stripped = line.strip()
            if not in_msg:
                if "<<" in line:
                    in_msg = True
                continue
            if stripped in ("EOF", ")\"", ")") or stripped.startswith("EOF"):
                break
            msg_lines.append(line)
        return "\n".join(msg_lines) if msg_lines else command
    match = re.search(r"""-m\s+["']([^"']+)["']""", command)
    if match:
        return match.group(1)
    return command


def validate_commit_message(message):
    if not message:
        return None
    first_line = message.split("\n")[0].strip()
    if first_line.startswith("Merge "):
        return None
    match = re.match(r"^(\w+):\s+(.+)", first_line)
    if not match:
        return (
            f"Commit message doesn't follow conventional format.\n"
            f"  Got: \"{first_line}\"\n"
            f"  Expected: \"type: description\"\n"
            f"  Allowed types: {', '.join(sorted(COMMIT_TYPES))}"
        )
    commit_type = match.group(1).lower()
    description = match.group(2)
    if commit_type not in COMMIT_TYPES:
        return f"Unknown commit type: \"{commit_type}\"\n  Allowed: {', '.join(sorted(COMMIT_TYPES))}"
    if len(description) < 10:
        return f"Commit description too short ({len(description)} chars, minimum 10)."
    if len(first_line) > 72:
        return f"Commit subject too long ({len(first_line)} chars, max 72)."
    return None


def check_branding(command):
    full_msg = extract_full_commit_message(command)
    for pattern in BRANDING_PATTERNS:
        match = pattern.search(full_msg)
        if match:
            return f"Commit contains Claude/Anthropic branding: \"{match.group()}\"\n  Remove all branding from the commit message."
    return None


def run_build(build_command, cwd):
    try:
        result = subprocess.run(build_command, cwd=cwd, capture_output=True, text=True, timeout=60, shell=True)
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            lines = output.splitlines()[-30:] if output else []
            return False, "\n".join(lines)
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Build timed out (60s)."
    except FileNotFoundError:
        return True, ""


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "")
    if not re.search(r"\bgit\s+commit\b", command):
        sys.exit(0)

    # Resolve UP to the workspace root: the build command and project-config
    # both belong to the root, not a drifted shell sub-directory. (No git
    # command is executed here -- only the commit string is inspected.)
    cwd = get_project_root(data.get("cwd"))
    project_config = load_project_config(cwd)

    # --- Check 1: Build verification ---
    if project_config:
        build_command = project_config.get("build_command", "")
        if build_command:
            success, output = run_build(build_command, cwd)
            if not success:
                print("Build failed. Fix errors before committing.", file=sys.stderr)
                if output:
                    print("\n" + output, file=sys.stderr)
                sys.exit(2)

    # --- Check 2: Commit message conventions ---
    commit_msg = extract_commit_message(command)
    msg_error = validate_commit_message(commit_msg)
    if msg_error:
        print("Commit message convention violation:", file=sys.stderr)
        print(msg_error, file=sys.stderr)
        sys.exit(2)

    # --- Check 3: No Claude/Anthropic branding ---
    branding_error = check_branding(command)
    if branding_error:
        print("Commit branding violation:", file=sys.stderr)
        print(branding_error, file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
