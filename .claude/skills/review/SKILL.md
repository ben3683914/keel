---
name: review
description: Run the full review pipeline manually (code, docs, security, tests)
disable-model-invocation: true
---

Run the complete review pipeline on current changes:
1. Code review: `get_relevant_modules` -> spawn code-reviewer agent (model: sonnet) -> `acknowledge_code_review`
2. Doc review: `get_relevant_docs` -> spawn docs-reviewer agent (model: sonnet) -> `acknowledge_review`
3. Security review: spawn security-reviewer agent (model: sonnet) with git diff -> `acknowledge_security_review`
4. Tests: `find_untested_files` -> spawn test-runner agent (model: sonnet) -> `acknowledge_tests`

Follow the review order enforcement. Stop if any step has critical/blocking issues.
