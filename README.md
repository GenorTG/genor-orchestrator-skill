# Genor's Orchestration Skill — Companion Package

[![ClawHub](https://img.shields.io/badge/ClawHub-genor--orchestrator-blue)](https://clawhub.com/packages/genor-orchestrator)
[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-brightgreen)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/GenorTG/genor-orchestrator-skill)](https://github.com/GenorTG/genor-orchestrator-skill/releases)

**Companion skill for the [Genor's Orchestrator Plugin](https://github.com/GenorTG/genor-orchestrator-plugin).**

Provides the dashboard web UI, coding workflow instructions, and operational scripts that work alongside the plugin's 12 tools and 8 lifecycle hooks.

---

## Components

### Dashboard Web UI (PM2 Sidecar)

A standalone Python HTTP server. Runs independently from the plugin — restarting does NOT affect OpenClaw.

```bash
pm2 start dashboard/server.py --name orchestration-dashboard --interpreter python3 -- 8766
# Open: http://localhost:8766
```

**API Endpoints:**

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/status` | GET | Quick overview |
| `/api/config` | GET/POST | Read/update routing config |
| `/api/models` | GET | List models (with filters) |
| `/api/models` | POST | Create or update a model |
| `/api/models` | DELETE | Delete a model |
| `/api/sessions` | GET | Session history |
| `/api/projects` | GET | All projects with stats |
| `/api/project-state` | GET | Detailed project state |
| `/api/project-doc` | GET/POST/DELETE | Read/write/delete project docs |
| `/api/all` | GET | Complete snapshot |

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/auto-populate-models.py` | Read OpenClaw config and populate model inventory |
| `scripts/check-models.sh [project]` | Check routing filter chain for a project |
| `scripts/check-prices.sh` | Fetch provider pricing |
| `scripts/init-project.sh <path> <name>` | Scaffold a new project |
| `scripts/test-model.sh <id>` | Test model endpoint |
| `scripts/run-model-discovery.sh` | Cron wrapper for auto-populate |
| `scripts/onboard.sh` | First-time setup wizard |

### SKILL.md — Coding Workflow Reference

The `SKILL.md` file is the instruction reference consumed by OpenClaw's skill system. It defines:
- 6-phase execution workflow (Init → Plan → Execute → Verify → Manage → Diagnose)
- Model routing decision tables
- Sub-agent protocol
- Tool fallback chains
- Conversational triggers

---

## Installation

This skill is installed **automatically** as part of the plugin setup. See the [plugin repo's SETUP.md](https://github.com/GenorTG/genor-orchestrator-plugin/blob/main/SETUP.md) for complete instructions.

Standalone install:

```bash
# Via ClawHub
clawhub install genor-orchestrator

# Or from source
git clone https://github.com/GenorTG/genor-orchestrator-skill.git
cd genor-orchestrator-skill
clawhub install .
```

---

## Related

- [Genor's Orchestrator Plugin](https://github.com/GenorTG/genor-orchestrator-plugin) — Runtime tools and hooks (required)
- [ClawHub Plugin Package](https://clawhub.com/packages/genor-orchestrator-plugin)
- [ClawHub Skill Package](https://clawhub.com/packages/genor-orchestrator)

## License

MIT-0 — Free to use, modify, redistribute. No attribution required.
