# Genor's Orchestration Skill

[![ClawHub](https://img.shields.io/badge/ClawHub-genor--orchestrator-blue)](https://clawhub.com/packages/genor-orchestrator)
[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-brightgreen)](LICENSE)

**Companion for [Genor's Orchestrator Plugin](https://github.com/GenorTG/genor-orchestrator-plugin).** Provides the dashboard web UI, coding workflow reference, and operational scripts.

---

## Components

### GenorBoard (port 8767)

| Tab | Feature |
|-----|---------|
| ⌂ Home | Activity feed, live session count, free-only mode toggle |
| 🔌 Gateway | Live gateway sessions with search, model, status, message count |
| ◆ Projects | Project docs, **Session Log** sub-tab (per-project, matched live + historical sessions with color-coded status), **Manager** sub-tab (active agents + session timeline) |
| ⬡ Models | Model inventory with quality grades, provider routing |
| 💬 Chat | SSE-pushed session list, message history, send to any session |
| 📋 Logs | Orchestration logs with level/source filters, quick filter buttons for Sessions/Context/Agents/System |
| ⚙ Settings | Free-only mode, theme, auto-refresh, dashboard config |

**NEW:** Header shows 🟢 **Project badge** ("Working on: project-name") when viewing a project

### Live Chat System

- **Push-based session list**: SSE endpoint at `/api/sse/live-sessions` streams real-time session data
- **Message history**: `/api/chat/history` fetches last 50 messages from any session
- **Async send**: `/api/chat/send` queues messages to an outbox; a WS bridge agent processes them
- **WS bridge** (`gateway-ws-bridge.js`): connects to Gateway WebSocket for push events, writes to `live-sessions.json`, processes `chat-outbox.json`

### Scripts

`auto-populate-models.py`, `check-models.sh`, `check-prices.sh`, `init-project.sh`, `test-model.sh`.

**SKILL.md**: Codified coding workflow (6 phases), model routing decision tables, sub-agent protocol, tool fallback chains.

---

## Quick Start

```bash
# Start the dashboard
pm2 start dashboard/serve.sh --name orchestration-dashboard

# Start the WebSocket bridge (for live chat + session data)
pm2 start dashboard/bridge.sh --name gw-ws-bridge

# Config: ensure sessions_send is allowed:
# Edit ~/.openclaw/openclaw.json:
# "gateway": {
#   "tools": {
#     "allow": ["sessions_send"]
#   }
# }
# Then restart gateway
```

The dashboard will be at **http://genorbox1:8767**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Browser (index.html)                        │
│   SSE ← /api/sse/live-sessions    POST /api/chat/send       │
└───────────────────┬─────────────────────────┬────────────────┘
                    │                         │
┌───────────────────▼─────────────────────────▼────────────────┐
│              server.py (Dashboard HTTP server)                │
│   ┌──────────────────┐   ┌─────────────────────────────┐     │
│   │ API endpoints     │   │ Writes chat-outbox.json     │     │
│   │ Static file serve │   │ Reads live-sessions.json    │     │
│   └──────────────────┘   └─────────────────────────────┘     │
└────────────────────────────────────────────────────────────────┘
                    │
┌───────────────────▼──────────────────────────────────────────┐
│          gateway-ws-bridge.js (Node.js WS client)             │
│   ┌──────────────────┐   ┌─────────────────────────────┐     │
│   │ WS connect + auth│   │ Reads chat-outbox.json       │     │
│   │ Subscribe events │   │ Sends via HTTP tools/invoke │     │
│   │ Write live JSON  │   │ Processes pending messages   │     │
│   └──────┬───────────┘   └─────────────────────────────┘     │
└──────────┼───────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────┐
│            OpenClaw Gateway (port 18789)                      │
│   ┌──────────────────┐   ┌─────────────────────────────┐     │
│   │ WebSocket        │   │ HTTP tools/invoke            │     │
│   │ Session events   │   │ sessions_send, list, history │     │
│   └──────────────────┘   └─────────────────────────────┘     │
└────────────────────────────────────────────────────────────────┘
```

---

## License

MIT-0
