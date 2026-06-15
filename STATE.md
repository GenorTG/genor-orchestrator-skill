# STATE.md — GenorBoard v4 + Live Chat

## Current Status

**GenorBoard** is live with 7 tabs: Home, Gateway, Projects, Models, Chat, Logs, Settings.

**Removed:** ■ Agents tab (was showing local tracker, not useful). **Renamed:** 📋 Sessions → 🔌 Gateway (now shows live gateway sessions with search/filter instead of a static list).

### Active Services (PM2)

| Name | Port | Script | Status |
|------|------|--------|--------|
| `orchestration-dashboard` | 8767 | `dashboard/serve.sh` → `server.py` | ✅ online |
| `gw-ws-bridge` | — | `dashboard/bridge.sh` → `gateway-ws-bridge.js` | ✅ online |

### Live Chat Architecture

```
┌──────────────┐    SSE /api/sse/live-sessions    ┌──────────────┐
│  ES Module   │ ←──────────────────────────────→ │   Browser    │
│  (index.html)│    POST /api/chat/send            │  (WebChat)   │
└──────┬───────┘    POST /api/chat/history         └──────────────┘
       │                                                   ▲
       │  writes chat-outbox.json                          │
       ▼                                                   │
┌──────────────┐    HTTP /tools/invoke              ┌──────┴───────┐
│ WS Bridge    │ ←──────────────────────────────→  │  Gateway WS  │
│ (node.js)    │    sessions.list, sessions.history │   (port 18789)│
└──────────────┘                                    └──────────────┘
```

### Files

| File | Purpose |
|------|---------|
| `dashboard/server.py` | HTTP server (ThreadingHTTPServer): serves dashboard HTML + API endpoints |
| `dashboard/gateway-ws-bridge.js` | WS bridge: session events → `live-sessions.json`, outbox processor |
| `dashboard/index.html` | SPA dashboard: 7 tabs (Home, Gateway, Projects, Models, Chat, Logs, Settings), SSE-connected chat, session viewer |
| `dashboard/serve.sh` | PM2 start script for server.py |
| `dashboard/bridge.sh` | PM2 start script for bridge.js |
| `orchestrator-data/live-sessions.json` | Shared session state (bridge writes, SSE reads) |
| `orchestrator-data/chat-outbox.json` | Message outbox (server writes, bridge processes) |

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sse/live-sessions` | SSE stream of live session data |
| POST | `/api/chat/history` | Fetch session history (50 msgs) |
| POST | `/api/chat/send` | Queue message to outbox (async send) |
| POST | `/api/*` | Various CRUD endpoints (models, config, etc.) |

### Gateway Config Required

```json
{
  "gateway": {
    "tools": {
      "allow": ["sessions_send"]
    }
  }
}
```

### Known Issues

- WS bridge reconnects every ~30s due to subscription not being properly acked
- HTTP polling fallback (30s) is secondary; `live-sessions.json` still updates
- Edge case: `gateway.tools.allow` may be protected — may need direct config file edit

### Next Steps

1. Fix WS bridge subscription to reduce reconnect churn
2. Add message dedup in the browser SSE event handler
3. Add typing indicator / message received confirmation
4. Mobile responsive tuning for chat pane (BL8000)
