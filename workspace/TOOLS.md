# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## Agent Roles

The user can invoke specialized AI agents using short prefixes. When you see these patterns, call the corresponding MCP tool immediately — do NOT answer the question yourself.

| Prefix | Tool | Agent |
|--------|------|-------|
| `em:` or `engineering manager:` | `run_engineering_manager` | Engineering Manager — decomposes requirements into task packets |
| `arch:` or `architect:` | `run_architect` | Architect — designs systems, data models, API contracts |
| `dev:` or `senior dev:` | `run_senior_dev` | Senior Developer — implements features and APIs |
| `jr:` or `junior dev:` | `run_junior_dev` | Junior Developer — tests, docs, small tasks |

### Examples
- `em: how to create instagram?` → call `run_engineering_manager("how to create instagram?")`
- `arch: design a notifications system` → call `run_architect("design a notifications system")`
- `dev: add a delete endpoint to the reminders API` → call `run_senior_dev("add a delete endpoint to the reminders API")`
- `jr: write tests for the storage module` → call `run_junior_dev("write tests for the storage module")`

You can also trigger these with natural language like "use the engineering manager to..." or "ask the architect to...".
