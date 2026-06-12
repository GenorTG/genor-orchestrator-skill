# Next-Gen Live Agent Orchestration Dashboard — Architecture Plan

## 1. Overview

Replace the basic Python HTTP server + inline HTML dashboard with a **production-grade, real-time agent orchestration dashboard** featuring a CLI/terminal aesthetic. No frameworks, no build step — pure Python `http.server` + SSE + standalone HTML.

## 2. Directory Layout

```
skill/dashboard/
├── PLAN.md              ← This document
├── server.py            ← Refactored Python dashboard server (port 8767)
├── index.html           ← Complete rewrite — CLI-terminal UI with SSE
├── serve.sh             ← PM2 launch script (update port)
├── state_cache.json     ← Internal cache file (written by SSE broadcaster)
└── lib/
    ├── __init__.py
    ├── datastore.py     ← DataStore class (file I/O, caching, parsing)
    ├── handler.py       ← HTTP request handler (routes, SSE, CORS)
    ├── sse.py           ← SSEBroadcaster class (poll + push)
    └── models.py        ← Model CRUD, filtering, enrichment
```

## 3. Architecture

### 3.1 Data Sources (Polled Every 2s)

| Source | Path | Format | Purpose |
|--------|------|--------|---------|
| Plugin state.json | `orchestrator-data/state.json` | JSON | Current project, task, model, agent, subagent_depth |
| Orchestrator JSONL | `orchestrator-data/logs/orchestrator.jsonl` | JSONL (newline-delimited) | All events: context, sessions, decisions, sync, routing |
| Sessions JSON | `orchestrator-data/projects/<name>/sessions.json` | JSON | Per-project session history |
| Models JSON | `orchestrator-data/models.json` | JSON | Full model inventory |
| Config JSON | `orchestrator-data/dashboard-config.json` | JSON | Free-only mode, disabled models, project configs |
| Session log MD | `orchestrator-data/session_log.md` | Markdown table | Session log (legacy) |
| Session markdown | `orchestrator-data/sessions/*.md` | Markdown | Individual session reports |

### 3.2 Python Server Components

#### DataStore (`lib/datastore.py`)
- Singleton cache with 2-second TTL
- Methods: `get_state()`, `get_logs(level, source, since, limit)`, `get_models()`, `get_config()`, `get_projects()`, `get_sessions()`, `get_activity(recent_count)`
- File watch: tracks mtime of each file; only re-reads on change
- JSONL tail: tracks byte offset for incremental reads
- Generates `state_cache.json` for SSE broadcaster

#### SSEBroadcaster (`lib/sse.py`)
- Maintains set of connected clients (file-like objects)
- Every 2 seconds: polls DataStore for delta, pushes events
- Event types: `activity` (new log lines), `state` (context change), `agents` (live sessions), `heartbeat`
- Client disconnect detection via socket write error + periodic cleanup

#### HTTP Handler (`lib/handler.py`)
- Routes all GET/POST/DELETE endpoints
- SSE endpoint at `/api/activity/stream`
- All existing v3 endpoints preserved
- CORS headers on all responses
- Professional error handling with HTTP status codes + JSON bodies

### 3.3 SSE Data Flow

```
Plugin writes to JSONL + state.json
         ↓
  DataStore polls every 2s (mtime-aware)
         ↓
  SSEBroadcaster computes delta events
         ↓
  Pushes to all connected browser clients
         ↓
  Index.html SSE eventSource.onmessage updates UI
```

### 3.4 SSE Event Format

```
event: activity
data: {"type":"activity","events":[{"ts":"...","level":"info","source":"context","msg":"..."},...]}

event: state
data: {"type":"state","project":"genor-orchestrator","task":"phase2","model":"opencode-go/deepseek-v4-flash"}

event: agents
data: {"type":"agents","agents":[{"name":"Amy","model":"...","task":"...","status":"active","subagents":2,"depth":1,"files":["..."]}]}

event: heartbeat
data: {"type":"heartbeat","ts":"...","server":"ok","models":38,"projects":4}
```

## 4. Frontend Architecture

### 4.1 Tab Structure

```
┌──────────────────────────────────────────────────────┐
│ [●] Dashboard Home  [■] Agents  [◆] Projects         │
│ [⬡] Models  [≡] Logs  [⚙] Settings                   │
├──────────────────────────────────────────────────────┤
│                                                       │
│   Tab-specific content area                           │
│                                                       │
├──────────────────────────────────────────────────────┤
│ ● Live | 3 agents | 38 models | 4 projects | 15:17   │
└──────────────────────────────────────────────────────┘
```

### 4.2 Home Tab — Live Activity Feed
- Terminal-scrolling feed (like `tail -f`)
- ANSI-color-coded log lines (info=blue, warn=yellow, error=red, success=green)
- Row types: log events, file changes, context switches, session starts/completes
- Auto-scroll toggle (lock/unlock)
- Filter by source/level
- Mini status cards: agents active, models online, projects, last decision

### 4.3 Agents Tab — Live Agent Grid
- Grid of cards, each showing:
  - Agent name + status badge (active/blocked/done/failed)
  - Current model + task (truncated)
  - Sub-agent count + depth indicator
  - Duration
  - Last file edit
- Click → expand with sub-agent tree visualization
- Poll + SSE updates agent state in real-time
- Empty state: "No agents active. Start a project to see agents work."

### 4.4 Projects Tab — Card Grid + Detail
- Card grid with: project name, session count, last activity, model allowlist badge
- Click → detail view with:
  - Doc tabs: STATE.md, ROADMAP.md, CONTEXT.md, NOTES.md (inline editor)
  - Sessions tab: session list table
  - Files tab: file browser + create/delete
  - Manager tab: live agent tree for this project
- Detail has "← Back to Projects" navigation

### 4.5 Models Tab — Full Inventory
- Same as current — stats row, filter bar, sortable table
- Preserved: multi-select + bulk disable/enable
- Model detail modal with read/edit toggle
- Speed star rating (clickable)
- Cost type badges

### 4.6 Logs Tab — Real-time Log Viewer
- Scrolling log viewer reading from JSONL
- Tail mode (follow new entries) or scroll-back
- Filters: level (info/warn/error), source, search text
- ANSI color coding
- Timestamp highlighting
- Auto-scroll toggle

### 4.7 Settings Tab
- Free-only toggle (live)
- Disabled models display
- Auto-refresh interval display
- Theme: dark only (terminal aesthetic)
- Server status info
- Data directory path
- Clear all caches button

### 4.8 Terminal Aesthetic
- Background: `#0d1117` (GitHub dark) — primary
- Cards: `#161b22` with `#30363d` borders
- Accent: `#58a6ff` (blue), `#3fb950` (green), `#f85149` (red)
- Font: `'JetBrains Mono', 'Cascadia Code', 'Fira Code', monospace` (with system fallback)
- ASCII/Unicode borders using box-drawing characters: `─ │ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼`
- Progress spinners: pure CSS keyframe animation
- Log lines: dimmed with ANSI-inspired coloring
- Status bar: always visible, terminal-style with dots and pills

## 5. API Endpoints

### GET Endpoints
| Path | Description |
|------|-------------|
| `/` or `/index.html` | Serve dashboard HTML |
| `/api/all` | Everything combined (for initial load) |
| `/api/status` | Server health, config summary |
| `/api/models` | Filtered model list (`?id=xxx` or `?all=1`) |
| `/api/config` | Full config |
| `/api/sessions` | Parsed session log |
| `/api/prices` | Price change log |
| `/api/projects` | Project list with last sessions |
| `/api/project-state?name=xxx` | Full project state |
| `/api/project-doc?name=xxx&file=yyy` | File content |
| `/api/activity` | Recent activity feed (last N log entries) |
| `/api/agents` | Live agent sessions (from state.json + sessions) |
| `/api/state` | Current orchestrator state |
| `/api/activity/stream` | SSE stream |

### POST Endpoints
| Path | Description |
|------|-------------|
| `/api/models` | Create/update model |
| `/api/config` | Update config |
| `/api/project-doc` | Write file |
| `/api/project-state` | Create/update project config |

### DELETE Endpoints
| Path | Description |
|------|-------------|
| `/api/models?id=xxx` | Delete model |
| `/api/project-doc?name=xxx&file=yyy` | Delete file |

## 6. Non-Goals
- No WebSocket dependency — SSE only
- No Node.js/npm build step — pure Python + vanilla JS
- No mobile responsiveness — desktop-only (1280px+ min-width)
- No React/Vue/Svelte — zero frameworks, zero build step
- No plugin modifications — reads from existing data files only

## 7. Migration
- Existing dashboard continues on port 8766 (PM2: `orchestration-dashboard`)
- New dashboard on port 8767 (PM2: `orchestration-dashboard-v2`)
- Once validated, update PM2 and swap ports
- All data files are shared between both instances (no write locks needed — reads only + config writes)
