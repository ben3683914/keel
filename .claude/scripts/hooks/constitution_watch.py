#!/usr/bin/env python3
"""FileChanged hook: monitors constitution article files for external edits.

Triggers on docs/constitution/*.md changes. Logs a warning if a constitution
file is modified outside the MCP tools (which would cause drift from SQLite).

Does not block -- just warns via stderr so Claude sees the drift.
"""

import json
import sys
from pathlib import Path


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # FileChanged hook receives the changed file path
    file_path = data.get("file_path", "")
    if not file_path:
        sys.exit(0)

    normalized = file_path.replace("\\", "/")

    # Only care about constitution article files
    if "docs/constitution/" not in normalized:
        sys.exit(0)

    if normalized.endswith(".md"):
        print(
            f"WARNING: Constitution file modified externally: {normalized}\n"
            "Constitution articles are auto-generated from SQLite. External edits "
            "will cause drift. Run check_constitution_drift to verify, or use "
            "propose_article/amend_article to make changes properly.",
            file=sys.stderr,
        )

    # Don't block (exit 0) -- just warn
    sys.exit(0)


if __name__ == "__main__":
    main()
