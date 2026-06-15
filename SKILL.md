---
name: "genor-orchestrator"
description: "Unified orchestration: plugin-driven model routing, session hooks, project context automation, sidecar dashboard"
homepage: "https://github.com/GenorTG/genor-orchestrator-skill"
metadata:
  {
    "openclaw": {
      "requires": { "bins": ["bash", "curl", "python3"] },
      "description": "Full-stack AI project orchestration: model management, routing, session logging, decision tracking, price monitoring, project scaffolding, coding workflow, plugin tools/hooks, and a real-time dashboard sidecar."
    }
  }
---

# Genor's Project Orchestration

> Single source of truth for agentic development work, model orchestration, project management, and context automation.

## Core Principles

1. **Codebase First** — Never touch code without understanding it first
2. **Plan Before Act** — `update_plan` for anything beyond one edit
3. **Verify Before Claim** — No completion claim without fresh evidence
4. **Self-Review** — Every output gets audited before delivery
5. **Fail Gracefully** — Every step has a fallback chain
6. **Document Everything** — Log sessions, decisions, architecture
7. **Model-Routing Compliance** — All LLM agents MUST consult project routing rules (free-only, disabled, per-project allowlist) before selecting a model or spawning a sub-agent.
8. **Context First** — Always call `orchestrator_set_context` before project work to enable automation hooks.
9. **Version Everything** — Every project session gets a versioned git commit before major checkpoints. Use `/genor-git-commit` or auto-tag after QA passes.
10. **QA Gate** — Every task run spawns a QA subagent (if configured) that tests the result before marking complete. No task is "done" until QA passes.

## Data Directory

All user data lives in `orchestrator-data/` (set `ORCHESTRATOR_DATA_DIR` to override).

```
orchestrator-data/
├── models.json             — model inventory
├── dashboard-config.json   — routing config (free-only, disabled, project allowlists)
├── live-sessions.json      — live gateway session snapshot from bridge
├── live-agents.json        — current session tracker state (project, model, action, status)
├── chat-outbox.json        — async message send queue
├── state.json              — current project state (written from plugin hooks)
├── price_changes.log       — price tracking
├── MODEL_CATALOG.md        — generated catalog
├── logs/                   — structured JSONL logs
├── adrs/                   — architecture decision records
├── projects/               — per-project data (CONTEXT, STATE, ROADMAP, BACKLOG, RECOVERY, sessions)
│   └── <name>/
│       ├── CONTEXT.md
│       ├── KEY_FILES.md
│       ├── RECOVERY.md
│       ├── BACKLOG.json
│       ├── sessions.json
│       └── ...
└── sessions/               — detailed session state files

> **Note:** `session_log.md` has been replaced by live bridge data and `projects/<name>/sessions.json` per-project.
```

### Live Agent Tracking
The plugin hooks write `live-agents.json` on every major event (session_start/end, context set, model resolve, prompt build, agent end). This gives the dashboard real-time visibility into:
- Which project the agent is currently working on
- What action it's performing
- Which model it's using
- Session key, uptime, token usage

## Architecture

The orchestrator has two components that work together:

### Plugin (Tools + Hooks)

Runs inside OpenClaw's plugin system — no separate process needed. Provides:

**Tools (12):**

| Tool | Purpose |
|------|---------|
| `orchestrator_set_context` | MANDATORY before project work — sets project + task, returns context doc with location, ToC, backlog, ADRs, recent sessions |
| `orchestrator_clear_context` | Clears active project context, disables auto-routing/logging |
| `orchestrator_get_status` | Quick overview: model counts, sessions, projects, current context |
| `orchestrator_get_models` | List models with filters (status, provider, search, project routing) |
| `orchestrator_check_models` | Check eligible models for a project (routing filter inspection) |
| `orchestrator_auto_populate` | Auto-populate models from OpenClaw gateway config |
| `orchestrator_log_session` | Log a session (auto-logged by hooks, use for manual/retro entries) |
| `orchestrator_log_decision` | Log an architecture decision (creates auto-numbered ADR) |
| `orchestrator_get_logs` | Query structured JSONL logs |
| `orchestrator_sync_project` | Sync project from disk (generates CONTEXT.md, KEY_FILES.md) |
| `orchestrator_get_project_docs` | List all orchestrator-managed documents for a project |

**Hooks (8) — auto-registered, no manual calls:**

| Hook | Automates |
|------|-----------|
| `session_start` | Track start time, reset sub-agent depth |
| `session_end` | Auto-log session to session_log.md, sessions.json, generate recovery doc |
| `subagent_spawned/ended` | Track sub-agent tree depth for context injection |
| `before_model_resolve` | Apply project routing filters (free-only, disabled, allowlists) |
| `before_prompt_build` | Inject project context into prompts (tasks, location, recent sessions) |
| `agent_end` | Observe session state |
| `gateway_stop` | Clean up maintenance timers |

### Sidecar: Dashboard Web UI (PM2)

The dashboard is a standalone Python HTTP server running as a PM2 process:

**Start:** `pm2 start ./dashboard/server.py --name orchestration-dashboard --interpreter python3 -- 8766`

**Provides:**
- Model inventory CRUD with sort, filter, search
- Routing config (free-only toggle, global disable, per-project allowlists)
- Session log viewer
- Config persistence to disk

> The dashboard runs independently of the plugin — restarting it does NOT affect OpenClaw or any running sessions.

## Project Context Automation

When `orchestrator_set_context(project="my-project", task="fix-bug")` is called:

1. **Sets active context** — all hooks use this for routing, logging, context injection
2. **Returns context doc** with location, File ToC, CONTEXT/STATE/ROADMAP summaries, open backlog tasks, recent ADRs, recent sessions, recovery doc availability
3. **Auto-injects** project state into the LLM's prompt every turn
4. **Auto-logs** when session ends (session_log.md, sessions.json, recovery doc)
5. **Auto-routes** models according to project allowlists

All data in `orchestrator-data/` survives OpenClaw session wipes — it's on the filesystem, not in session storage.

## Model Population

Models are **automatically populated** from OpenClaw's own gateway configuration. The script reads `openclaw.json` and extracts all configured model entries from providers, agent defaults, and routing chains. It merges into `orchestrator-data/models.json`, preserving all manually-curated fields (tier, speed_rating, capabilities, notes, research). Models in the catalog not found in the config are kept as-is (never deleted).

Auto-population runs nightly via cron. Manual edits (tier, speed, pricing, routing rules) are done through the Dashboard WebUI.

## Model Routing

### Routing Decision Table

| Task Type | Primary | Fallback 1 | Fallback 2 |
|-----------|---------|------------|------------|
| Heavy coding | Best available | ACP agent | Fast cloud |
| Quick edits | Fast cloud | Free tier | Local |
| Research | Best reasoning | Free tier | Local |
| Vision | Cloud vision | Local | Describe |
| Planning / design | Best reasoning | Free tier | Fast cloud |
| Docs / summaries | Free tier | Fast cloud | Local |

### MANDATORY: Check Configuration Before Every Routing Decision

**Before selecting any model or spawning a sub-agent:**

1. Read `dashboard-config.json` (or call `GET /api/config`)
2. Identify the current project name
3. Apply the filtering chain:
   - **Global free-only**: If `free_only_mode: true`, eliminate all paid models
   - **Global disabled**: Remove any model in `disabled_models` list
   - **Per-project allowlist**: If the project has a non-empty `model_allowlist`, ONLY those models are eligible
   - **Per-project free-only**: If the project has `free_only: true`, eliminate paid models from the allowlist
4. Only then select a model from the remaining eligible set
5. If no eligible model exists, report the conflict — do NOT silently use a banned model

**CLI shortcut:** `bash scripts/check-models.sh my-project-name`

### Filtering Chain (applied in order)

1. Global free-only removes paid models (if enabled)
2. Global disabled removes blocked models
3. Per-project allowlist keeps only whitelisted (if set)
4. Per-project free-only removes paid from allowlist (if enabled)

### API Endpoints (Dashboard WebUI Sidecar)

- `GET /api/config` — read config
- `POST /api/config` — update config
- `GET /api/models` — filtered model list
- `GET /api/models?project=<name>` — filtered for specific project
- `GET /api/models?all=1` — full unfiltered list
- `GET /api/models?id=<id>` — single model with `disabled` flag
- `POST /api/models` — create or update model
- `DELETE /api/models?id=<id>` — delete model
- `GET /api/status` — quick status
- `GET /api/all` — everything

## Sub-Agent Protocol

### Step 0: Set Project Context (MANDATORY)

Call `orchestrator_set_context(project="my-project", task="fix-bug")` before spawning any sub-agent.

This enables auto-routing, auto-logging, context injection, and background maintenance.

### Step 1: Check Model Routing Configuration

```bash
bash scripts/check-models.sh my-project-name
```

### Injection Template

Every spawned sub-agent prompt MUST include:

```
IMPORTANT: Follow orchestration conventions:
- BEFORE selecting any model: read dashboard-config.json, apply routing filters for the project. Run: bash scripts/check-models.sh <project-name>
- Understand the codebase first (exec find as fallback)
- Plan before coding (update_plan or mental plan)
- Verify before claiming (build, test, screenshot)
- Self-review output before returning
- Use fallback chains when tools are unavailable
```

## Execution Workflow

### Phase 0: Init
Understand the codebase, search memory, research.

### Phase 1: Plan
Call `update_plan`. Size the work: small (1-3 files), medium (3-8), large (8+ → decompose with workboard).

### Phase 2: Execute

| Scenario | Primary | Fallback |
|----------|---------|----------|
| Single-line edit | `edit` tool | `exec sed` |
| Multi-file change | ACP coding agent | Manual `edit` |
| Research | Sub-agent | Web search |
| Debugging | Phase 5 protocol | Mental trace |
| Testing | Test framework | Manual |
| Browser testing | Browser tool | `curl` |

### Phase 3: Verify
Build → Test → Lint → Screenshot (if UI). No claim without evidence.

### Phase 4: Manage
Update CONTEXT.md, STATE.md, BACKLOG.json after every session.

### Phase 5: Diagnose
Reproduce → Hypothesise (3-5 causes) → Instrument one variable → Fix → Regression test.

### Phase 6: Tool Fallbacks

| Tool | Fallback chain |
|------|---------------|
| Codebase discovery | `exec find` → `exec ls -R` → read key files |
| `update_plan` | mental plan → STATE.md note |
| ACP coding agent | CLI variant → sub-agent → manual edit |
| `edit` tool | `exec sed` → `write` full file |
| Build | `tsc --noEmit` → `node --check` |
| Test | specific test file → manual |
| Vision | cloud → local → describe |
| Memory search | `lcm_grep` → `exec grep` |

## Scripts

| Script | Purpose |
|--------|---------|
| `bash/scripts/onboard.sh` | First-time setup |
| `bash/scripts/init-project.sh <path> <name>` | Scaffold project |
| `bash/scripts/log-session.sh ...` | Log session (legacy, plugin hooks preferred) |
| `bash/scripts/log-decision.sh ...` | Log ADR (legacy, plugin tool preferred) |
| `bash/scripts/check-prices.sh` | Price check |
| `bash/scripts/discover-models.sh` | Probe providers |
| `bash/scripts/test-model.sh <id>` | Test connectivity |
| `bash/dashboard/serve.sh` | Start dashboard |
| `bash/scripts/check-models.sh [project]` | MANDATORY: Check eligible models before routing |
| `python3 ./scripts/auto-populate-models.py` | Auto-populate models from OpenClaw gateway config |
| `bash/scripts/run-model-discovery.sh` | Wrapper for cron-based auto-population |

## Conversational Triggers

- "start dashboard" → `bash dashboard/serve.sh` or `pm2 start ...`
- "onboard project X" → `bash scripts/init-project.sh <path> <name>`
- "check prices" → `bash scripts/check-prices.sh`

## Design Grilling

Before significant architectural work, conduct a structured interview:
1. One question at a time, wait for feedback
2. Challenge terms that conflict with existing context docs
3. Propose precise canonical terms for vague language
4. Stress-test with edge cases
5. Cross-reference with code; surface contradictions

Generate: CONTEXT.md (glossary), ADRs (decisions), summary.

**ADR criteria** (all three must be true): hard to reverse, surprising without context, real trade-off.

## References

| Resource | Path |
|----------|------|
| Full documentation | `./references/README.md` |
| Onboarding guide | `./references/ONBOARDING.md` |
| Execution reference | `./references/EXECUTION.md` |

## Versioning & Git Workflow

Every project should follow this versioning discipline:

### When to Commit
- After each completed task (post-QA if QA configured)
- Before any significant refactor
- After documentation updates
- At the end of every work session

### How to Commit
1. **Bump version**: Patch (1.2.3 → 1.2.4) for fixes/minor changes; Minor (1.2.3 → 1.3.0) for features; Major (1.2.3 → 2.0.0) for breaking changes.
2. **Commit message**: `v<version>: <action> — <summary>`
   - e.g. `v1.2.4: fix — correct session key filter in session_start hook`
3. **Tag**: Every commit gets a `v<version>` tag.
4. **Push**: Push commits + tags to remote.

### Using `/genor-git-commit`
The plugin slash command `/genor-git-commit` automates this:
- Detects the current project from orchestrator context
- Stages all changes (`git add -A`)
- Reads version from `package.json`, bumps patch
- Commits with auto-generated message
- Tags and pushes

### Auto-Commit on Session End
When `workflow.auto_commit` is enabled in the project config, the plugin **automatically** commits and tags changes at the end of every session hook. No manual step needed.

---

## Workflow Enforcement Engine

The plugin includes an optional 6-phase workflow enforcement engine:

```
Analyze → Plan → Document → Work → Log → Finish
```

### How It Works
1. **Configure** per-project in `dashboard-config.json`:
   ```json
   {
     "projects": {
       "my-project": {
         "location": "/path/to/project",
         "workflow": {
           "enabled": true,
           "include_qa": true,
           "auto_commit": true,
           "qa_retries": 3,
           "skip_phases": []
         }
       }
     }
   }
   ```
2. **Set context** with `orchestrator_set_context` — workflow auto-initializes
3. **Advance phases** with `orchestrator_advance_phase` — blocks backward transitions
4. **Complete** — auto-commit fires on `session_end` if enabled

### 6 Phases
| Phase | Purpose | Tool/Mechanism |
|-------|---------|---------------|
| **Analyze** | Read codebase, understand requirements | `read`, `exec find`, memory search |
| **Plan** | Design solution, choose approach | `update_plan`, `sessions_spawn` |
| **Document** | Write ADRs, update CONTEXT/STATE | `orchestrator_log_decision` |
| **Work** | Implement the change | Code edits, builds, tests |
| **Log** | Record session, decisions, outcomes | `orchestrator_log_session` |
| **Finish** | Wrap up, summary, QA trigger | Auto-handled by plugin |

### Phase Advancement
```typescript
orchestrator_advance_phase({ phase: "plan" })  // jump to specific phase (must be forward)
orchestrator_advance_phase({})                    // auto-advance to next phase
orchestrator_advance_phase({ skip: true })        // skip current phase
```

### QA Loop (Coming in v0.6.0)
When `include_qa: true`:
1. After `Finisn`, plugin auto-spawns a QA subagent
2. QA runs tests, checks code, lints docs
3. If QA fails → phase resets to "work" for fixes
4. Max retries: `qa_retries` (default 3)
5. After QA passes → auto-commit fires

### Manual Git Commands
When auto-commit isn't desired (e.g. during active development), use:
```bash
git add -A && git commit -m "wip: desc"
```
Then squash before final commit.

### Docs Must Match Reality
After every major change or before pushing:
1. Run `git diff --stat` to check what changed
2. Update README, SKILL.md, or any docs that reference changed behavior
3. Run lint/checks on docs if available
4. Only push when docs are accurate
| Debugging guide | `./references/DEBUGGING.md` |
| Fallback tables | `./references/FALLBACKS.md` |
| Routing table | `./ROUTING.md` |
| Model catalog | `orchestrator-data/MODEL_CATALOG.md` |
| Dashboard | `http://localhost:8766` (when running) |
