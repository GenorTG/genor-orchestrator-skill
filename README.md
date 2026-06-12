# Genor's Orchestration Skill

[![ClawHub](https://img.shields.io/badge/ClawHub-genor--orchestrator-blue)](https://clawhub.com/packages/genor-orchestrator)
[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-brightgreen)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/GenorTG/genor-orchestrator-skill)](https://github.com/GenorTG/genor-orchestrator-skill/releases)
[![Maintained](https://img.shields.io/badge/Maintained-yes-brightgreen)](https://github.com/GenorTG/genor-orchestrator-skill)

**Companion skill for the [Genor's Orchestrator Plugin](https://github.com/GenorTG/genor-orchestrator-plugin).** Provides the dashboard web UI, execution workflows, model routing documentation, and operational scripts that work alongside the plugin's tools and hooks.

The **plugin** provides the runtime backbone (12 tools + 8 lifecycle hooks). This **skill** provides the instructions, visual interface, and supporting tooling. They are designed to work together for a complete orchestration experience.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  Genor's Orchestrator                │
├─────────────────────────┬────────────────────────────┤
│    PLUGIN (runtime)      │    SKILL (this repo)      │
│                         │                            │
│  ┌───────────────────┐  │  ┌──────────────────────┐  │
│  │ 12 Tools          │  │  │ Dashboard Web UI     │  │
│  │ • set_context     │  │  │ • Model CRUD         │  │
│  │ • get_models      │  │  │ • Routing config     │  │
│  │ • log_decision    │  │  │ • Session viewer     │  │
│  │ • sync_project    │  │  │ • Project management │  │
│  │ • ...             │  │  └──────────────────────┘  │
│  └───────────────────┘  │                            │
│  ┌───────────────────┐  │  ┌──────────────────────┐  │
│  │ 8 Hooks           │  │  │ Coding Workflow      │  │
│  │ • session_start   │  │  │ • 6 execution phases │  │
│  │ • session_end     │  │  │ • Fallback chains    │  │
│  │ • before_model_   │  │  │ • Debugging protocol │  │
│  │   resolve         │  │  │ • Verification steps │  │
│  │ • before_prompt_  │  │  └──────────────────────┘  │
│  │   build           │  │                            │
│  │ • ...             │  │  ┌──────────────────────┐  │
│  └───────────────────┘  │  │ Scripts              │  │
│                         │  │ • auto-populate      │  │
│  Runs inside OpenClaw   │  │ • check-models       │  │
│  No separate process    │  │ • check-prices       │  │
│                         │  │ • project scaffolding│  │
│                         │  └──────────────────────┘  │
└─────────────────────────┴────────────────────────────┘
```

---

## Components

### Dashboard Web UI (PM2 Sidecar)

A standalone Python HTTP server that provides a visual interface for managing the orchestrator. Runs independently from the plugin — restarting it does **not** affect OpenClaw.

```bash
# Start
pm2 start dashboard/server.py --name orchestration-dashboard --interpreter python3 -- 8766

# Open in browser
open http://localhost:8766
```

**Capabilities:**
- **Model Inventory** — View, search, sort, filter all registered models. Edit tier, speed ratings, pricing, capabilities. Bulk enable/disable.
- **Model CRUD** — Add new models, update existing ones, delete stale entries. Full form editor for all fields.
- **Routing Configuration** — Toggle global free-only mode, disable models globally, set per-project model allowlists.
- **Session Viewer** — Browse session history with project/task/model/status columns.
- **Project Management** — Configure project locations, view per-project documents and sessions.
- **Configuration Persistence** — All changes saved immediately to `dashboard-config.json`.

**API Endpoints:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/status` | GET | Quick overview (free-only, disabled count, projects) |
| `/api/config` | GET/POST | Read/update routing configuration |
| `/api/models` | GET | List models (with filters for project, status, all) |
| `/api/models` | POST | Create or update a model |
| `/api/models` | DELETE | Delete a model |
| `/api/sessions` | GET | Session history |
| `/api/projects` | GET | List all projects with stats |
| `/api/project-state` | GET | Detailed project state (sessions, docs, config) |
| `/api/project-doc` | GET/POST/DELETE | Read/write/delete project documents |
| `/api/all` | GET | Complete snapshot (models, sessions, projects, config, status) |

### Coding Workflow

Structured 6-phase execution protocol defined in `SKILL.md`:

1. **Init** — Codebase discovery, memory search, research
2. **Plan** — Break down work, call `update_plan`
3. **Execute** — Primary tool → fallback chain for every operation
4. **Verify** — Build → Test → Lint → Screenshot. No claim without evidence.
5. **Manage** — Update project docs after every session
6. **Diagnose** — Reproduce → Hypothesise → Instrument → Fix → Regress

Each phase has defined fallback chains for tool unavailability.

### Model Routing

Layered routing filter chain enforced by the plugin's `before_model_resolve` hook:

```
[All Models] → [Global Free-Only] → [Global Disabled] → [Project Allowlist] → [Project Free-Only]
```

Defined in `ROUTING.md` with routing decision tables per task type (coding, research, vision, planning, docs).

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/auto-populate-models.py` | Read OpenClaw config and merge into model inventory (runs nightly via cron) |
| `scripts/check-models.sh <project>` | Check eligible models through the routing filter chain |
| `scripts/check-prices.sh` | Check provider pricing pages |
| `scripts/init-project.sh <path> <name>` | Scaffold a new project with orchestrator structure |
| `scripts/test-model.sh <id>` | Test model endpoint connectivity |
| `scripts/run-model-discovery.sh` | Wrapper for cron-based auto-population |
| `scripts/onboard.sh` | First-time orchestrator setup |
| `dashboard/serve.sh` | Start the dashboard web UI |

---

## Getting Started

### 1. Install the Plugin

```bash
openclaw plugins install genor-orchestrator-plugin
openclaw plugins enable genor-orchestrator-plugin
```

### 2. Install the Skill

```bash
clawhub install genor-orchestrator
```

### 3. Start the Dashboard

```bash
cd ./skills/genor-orchestrator
pm2 start dashboard/server.py --name orchestration-dashboard --interpreter python3 -- 8766
pm2 save
```

### 4. Set Project Context

In your OpenClaw session:
```typescript
orchestrator_set_context(project="my-project", task="start-development")
```

The plugin hooks handle logging, routing, and context injection automatically.

---

## Configuration

The dashboard serves data from `orchestrator-data/` (configurable via `ORCHESTRATOR_DATA_DIR` env or the plugin's `orchestratorDataDir` config):

```
orchestrator-data/
├── models.json               — Model inventory
├── dashboard-config.json     — Routing configuration
├── session_log.md            — Session history
├── logs/orchestrator.jsonl   — Structured logs (auto-rotated)
├── adrs/                     — Architecture Decision Records
├── sessions/                 — Detailed session files
└── projects/<name>/          — Per-project data
    ├── CONTEXT.md
    ├── KEY_FILES.md
    ├── RECOVERY.md
    ├── BACKLOG.json
    └── sessions.json
```

---

## Related

- [Genor's Orchestrator Plugin](https://github.com/GenorTG/genor-orchestrator-plugin) — Runtime tools and hooks (required)
- [OpenClaw Documentation](https://docs.openclaw.ai) — Official OpenClaw docs
- [ClawHub Registry](https://clawhub.com) — Browse and publish skills and plugins

---

## License

MIT-0 — Free to use, modify, and redistribute. No attribution required.
