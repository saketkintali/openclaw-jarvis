# Agent Roles

Ready-to-use agent role definitions for OpenClaw.  
Each `.prompt.md` file is a system prompt — feed it into `sessions_spawn` to get that agent.

---

## The Team

| Role | File | Model | When to use |
|------|------|-------|-------------|
| Engineering Manager | `engineering-manager.prompt.md` | sonnet/opus | Coordinating a full team, decomposing big requirements |
| Architect | `architect.prompt.md` | sonnet | Designing systems, data models, API contracts |
| Senior Dev | `senior-dev.prompt.md` | sonnet | Building features, APIs, full implementations |
| Junior Dev | `junior-dev.prompt.md` | haiku | Tests, docs, small bug fixes, well-defined tasks |

---

## How to Invoke

### Single agent (tell Jarvis)
```
"Use the senior dev to add a delete endpoint to the expense API"
"Get the architect to design a notifications system"
"Have the junior dev write tests for the storage module"
```

### Full team (for new apps)
```
"Run the full team on: build a TypeScript habit tracker"
```
Flow: EM decomposes → Architect designs → Senior Dev builds → Junior Dev tests

### When to use which
| Situation | Use |
|-----------|-----|
| Add a feature to existing code | Senior Dev only |
| Fix a bug | Senior Dev only |
| Write tests for existing code | Junior Dev only |
| Design a new system from scratch | Architect → Senior Dev |
| Build a whole new app | Full team (EM first) |
| Decompose a large requirement | EM only |

---

## File Ownership Rules
When multiple agents work in parallel, each file must have exactly one owner.
- Owner: can read and write
- Non-owner: read-only

This prevents merge conflicts and keeps responsibility clear.

---

## Adding New Roles
1. Copy an existing `.prompt.md` as a template
2. Update identity, tools, workflow, and output format
3. Add it to the table above
4. Tell Jarvis: "we have a new [role] agent now"
