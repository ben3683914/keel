# Agent Roles

## Architecture

The main agent is the **architect and orchestrator**. It:
- Designs with the user (questions one at a time, collaborative)
- Manages all MCP tool interactions
- Delegates ALL implementation to agent teams
- NEVER writes source code directly

Sub-agents are **specialists**. They:
- Write code, review code, run tests
- Cannot call MCP tools
- Receive context from the main agent, return summaries
- Can run in parallel for independent work

## Review Agents

| Agent | Purpose | When |
|-------|---------|------|
| code-reviewer | Code quality audit | After every source change |
| docs-reviewer | Documentation currency check | After code review passes |
| security-reviewer | Pre-commit security audit | After doc review passes |
| test-runner | Create and run tests | After security review passes |

All review agents use `model: "sonnet"` for efficiency.

## Review Order

Enforced: code -> docs -> security -> tests. Each step requires the previous to complete.
