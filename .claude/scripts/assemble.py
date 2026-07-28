#!/usr/bin/env python3
"""Assemble CLAUDE.md and settings.json from scaffold partials based on project mode.

Derives the mode from the workspace-level `enforcement` setting in
.claude/project-config.json ('minimal' -> scratchpad, otherwise -> project) and
concatenates the appropriate partial files from .claude/scaffolds/ to produce the
final CLAUDE.md and settings.json.

Usage:
    python assemble.py                    # Derive mode from project-config.json
    python assemble.py --mode scratchpad  # Override mode (useful for testing)
    python assemble.py --project-root /path/to/repo
"""

import argparse
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path


# --- Mode-to-partials mapping ---

CLAUDE_MD_PARTIALS = {
    "scratchpad": [
        "base.md",
        "mode-header-scratchpad.md",
        "session-start-base.md",
        "instructions-scratchpad.md",
        "skills-scratchpad.md",
    ],
    "project": [
        "base.md",
        "mode-header-project.md",
        "session-start-base.md",
        "session-start-project.md",
        "agent-teams.md",
        "instructions-project.md",
        "skills-project.md",
        "doc-map.md",
    ],
    "tutorial": [
        "base.md",
        "tutorial.md",
    ],
}

SETTINGS_PARTIALS = {
    "scratchpad": ["base.json"],
    "project": ["base.json", "hooks-enforcement.json"],
    "tutorial": ["base.json"],
}


def find_project_root(start: Path | None = None) -> Path:
    """Find project root by looking for .claude/ directory or using git."""
    if start:
        return start

    # Try git rev-parse first
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Walk up from cwd
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".claude").is_dir():
            return parent

    return cwd


def load_project_config(root: Path) -> dict:
    config_path = root / ".claude" / "project-config.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def deep_merge_hooks(base: dict, overlay: dict) -> dict:
    """Deep merge two settings dicts, concatenating hook arrays."""
    result = deepcopy(base)

    for key, value in overlay.items():
        if key == "_comment":
            continue
        if key == "hooks" and "hooks" in result:
            # Merge hook events: concatenate arrays for each event type
            for event, entries in value.items():
                if event in result["hooks"]:
                    result["hooks"][event].extend(entries)
                else:
                    result["hooks"][event] = deepcopy(entries)
        else:
            result[key] = deepcopy(value)

    return result


def assemble_claude_md(root: Path, mode: str) -> str:
    """Concatenate CLAUDE.md partials for the given mode."""
    scaffolds_dir = root / ".claude" / "scaffolds"
    partials = CLAUDE_MD_PARTIALS.get(mode, CLAUDE_MD_PARTIALS["project"])

    sections = []
    for partial_name in partials:
        partial_path = scaffolds_dir / partial_name
        if not partial_path.exists():
            print(f"  WARNING: missing partial {partial_name}", file=sys.stderr)
            continue
        content = partial_path.read_text(encoding="utf-8").rstrip()
        sections.append(content)

    return "\n\n".join(sections) + "\n"


def assemble_settings(root: Path, mode: str) -> dict:
    """Deep-merge settings.json partials for the given mode."""
    settings_dir = root / ".claude" / "scaffolds" / "settings"
    partials = SETTINGS_PARTIALS.get(mode, SETTINGS_PARTIALS["project"])

    merged = {}
    for partial_name in partials:
        partial_path = settings_dir / partial_name
        if not partial_path.exists():
            print(f"  WARNING: missing settings partial {partial_name}", file=sys.stderr)
            continue
        try:
            data = json.loads(partial_path.read_text(encoding="utf-8"))
            merged = deep_merge_hooks(merged, data)
        except json.JSONDecodeError as e:
            print(f"  ERROR: invalid JSON in {partial_name}: {e}", file=sys.stderr)

    return merged


def preserve_user_keys(existing: dict, assembled: dict) -> dict:
    """Preserve user-added keys from existing settings.json that aren't managed by scaffolds."""
    managed_keys = {"model", "permissions", "enableExperimentalAgentTeams", "hooks", "_comment"}
    result = deepcopy(assembled)

    for key, value in existing.items():
        if key not in managed_keys:
            result[key] = value

    return result


def main():
    parser = argparse.ArgumentParser(description="Assemble CLAUDE.md and settings.json from scaffolds")
    parser.add_argument("--mode", choices=["scratchpad", "project", "tutorial"],
                        help="Override project mode (default: derive from enforcement in project-config.json)")
    parser.add_argument("--project-root", type=Path, help="Project root directory")
    args = parser.parse_args()

    root = find_project_root(args.project_root)
    scaffolds_dir = root / ".claude" / "scaffolds"

    if not scaffolds_dir.is_dir():
        print(f"ERROR: scaffolds directory not found at {scaffolds_dir}", file=sys.stderr)
        sys.exit(1)

    # Determine mode.
    # Mode is derived from workspace-level enforcement: 'minimal' -> scratchpad,
    # anything else (e.g. 'full') -> project. The --mode CLI flag overrides this.
    config = load_project_config(root)
    if args.mode:
        mode = args.mode
    else:
        mode = "scratchpad" if config.get("enforcement") == "minimal" else "project"

    if mode not in CLAUDE_MD_PARTIALS:
        print(f"ERROR: unknown mode '{mode}'", file=sys.stderr)
        sys.exit(1)

    print(f"Assembling for mode: {mode}")

    # Assemble CLAUDE.md
    claude_md = assemble_claude_md(root, mode)
    claude_md_path = root / "CLAUDE.md"
    claude_md_path.write_text(claude_md, encoding="utf-8", newline="\n")
    print(f"  Wrote {claude_md_path} ({len(claude_md.splitlines())} lines)")

    # Assemble settings.json
    assembled_settings = assemble_settings(root, mode)

    settings_path = root / ".claude" / "settings.json"
    existing_settings = {}
    if settings_path.exists():
        try:
            existing_settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    final_settings = preserve_user_keys(existing_settings, assembled_settings)
    settings_json = json.dumps(final_settings, indent=2) + "\n"
    settings_path.write_text(settings_json, encoding="utf-8", newline="\n")
    print(f"  Wrote {settings_path}")

    # Flip template_dev off once onboarding commits an enforcement level
    # (single / multi / scratch all set `enforcement`; the flip keys on that, not on
    # `projects[]`, since scaffold-only maintainers never write enforcement).
    # The pristine template ships enforcement="" and correctly stays in dev mode.
    # A CLI --mode override does not write `enforcement`, so it never flips the flag
    # (lets maintainers test scaffolds without disabling the guardrail).
    if config.get("enforcement") and config.get("template_dev") is True:
        config["template_dev"] = False
        config_path = root / ".claude" / "project-config.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"  Flipped template_dev -> false in {config_path}")

    print("Done.")
    sys.exit(0)


if __name__ == "__main__":
    main()
