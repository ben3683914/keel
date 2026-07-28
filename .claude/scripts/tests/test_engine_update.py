"""engine-update validation: JSONC comment stripping is string-aware.

Regression for the v2.0.0 bug where the block-comment regex (/\\*.*?\\*/) mangled
glob patterns in .vscode/settings.json merges: the /* inside "**/*.pyc" and the
*/ inside "**/bin" were treated as a comment span, eating the line and turning
"**/bin/Debug" into "**bin/Debug".

    .claude/venv/bin/python .claude/scripts/tests/test_engine_update.py
"""

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / ".claude" / "scripts" / "shared"))
_spec = importlib.util.spec_from_file_location(
    "engine_update", REPO / ".claude" / "scripts" / "engine-update.py"
)
eu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eu)

_checks = 0
_failures = []


def check(label, cond):
    global _checks
    _checks += 1
    print(f"  {'ok:  ' if cond else 'FAIL:'} {label}")
    if not cond:
        _failures.append(label)


def main():
    strip = eu._strip_jsonc_comments

    # 1. Globs containing /* and */ INSIDE strings must be preserved (the bug).
    src = ('{\n  "search.exclude": {\n'
           '    "**/__pycache__": true,\n'
           '    "**/*.pyc": true,\n'
           '    "**/bin/Debug": true,\n'
           '    "**/bin/Release": true\n  }\n}')
    d = json.loads(strip(src))
    excl = d["search.exclude"]
    check("glob **/*.pyc preserved", "**/*.pyc" in excl)
    check("glob **/bin/Debug preserved", "**/bin/Debug" in excl)
    check("no mangled **bin/Debug key", "**bin/Debug" not in excl)
    check("all 4 exclude keys intact", len(excl) == 4)

    # 2. Real // line comments are stripped...
    d2 = json.loads(strip('{\n  // a comment\n  "a": 1\n}'))
    check("// line comment stripped", d2 == {"a": 1})

    # 3. ...but // inside a string (e.g. a URL) is NOT stripped.
    d3 = json.loads(strip('{"url": "http://example.com", "a": 1}'))
    check("// inside string preserved", d3 == {"url": "http://example.com", "a": 1})

    # 4. Real /* block */ comments are stripped, even across lines.
    d4 = json.loads(strip('{\n  "a": 1, /* block\n  comment */ "b": 2\n}'))
    check("/* block */ comment stripped", d4 == {"a": 1, "b": 2})

    # 5. A value that itself contains */ is preserved.
    d5 = json.loads(strip('{"glob": "src/**/*"}'))
    check("value containing */ preserved", d5 == {"glob": "src/**/*"})

    print()
    if _failures:
        print(f"ENGINE-UPDATE: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"ENGINE-UPDATE: all {_checks} checks passed")


if __name__ == "__main__":
    main()
