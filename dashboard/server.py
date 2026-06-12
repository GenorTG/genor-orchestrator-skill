#!/usr/bin/env python3
"""Orchestration Dashboard v4 — Next-gen live agent dashboard with SSE, activity feed, agent tracking."""

import json, os, http.server, urllib.parse, time, threading, io, re
from pathlib import Path

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DATA = os.path.join(os.path.expanduser("~/.openclaw/workspace/orchestrator-data"))
DATA_DIR = os.environ.get("ORCHESTRATOR_DATA_DIR", _DEFAULT_DATA)
PORT = int(os.environ.get("DASHBOARD_PORT", "8767"))
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_cache.json")
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

# File paths
MODELS_FILE = os.path.join(DATA_DIR, "models.json")
CONFIG_FILE = os.path.join(DATA_DIR, "dashboard-config.json")
JSONL_FILE = os.path.join(DATA_DIR, "logs", "orchestrator.jsonl")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
SESSION_LOG_FILE = os.path.join(DATA_DIR, "session_log.md")
PRICES_FILE = os.path.join(DATA_DIR, "price_changes.log")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")

# ────────────────────────────────────────────────────────────
# DataStore — file I/O with mtime-aware caching + JSONL tail
# ────────────────────────────────────────────────────────────

class DataStore:
    """Thread-safe file I/O with mtime-aware caching and JSONL incremental reading."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}  # path -> (mtime, data)
        self._jsonl_pos = {}  # path -> byte_offset
        self._poll_count = 0

    def _read_file(self, path, parser=None, cache=True):
        """Read a file with mtime caching. Returns parsed data or None."""
        with self._lock:
            try:
                mtime = os.path.getmtime(path)
                cached = self._cache.get(path)
                if cached and cached[0] == mtime and cache:
                    return cached[1]

                with open(path) as f:
                    raw = f.read()

                result = parser(raw) if parser else raw
                if cache:
                    self._cache[path] = (mtime, result)
                return result
            except (FileNotFoundError, IOError, json.JSONDecodeError) as e:
                return None

    def _read_json(self, path, cache=True):
        return self._read_file(path, parser=json.loads, cache=cache)

    def invalidate(self, path):
        """Force re-read on next access."""
        with self._lock:
            self._cache.pop(path, None)

    def invalidate_all(self):
        """Clear all caches."""
        with self._lock:
            self._cache.clear()
            self._jsonl_pos.clear()

    # ── Specific data accessors ──

    def get_state(self):
        """Return current orchestrator state from state.json."""
        data = self._read_json(STATE_FILE)
        if not data:
            return {
                "project": None, "task": None, "model": None,
                "agent": None, "timestamp": None, "subagent_depth": 0,
                "agents": []
            }
        data.setdefault("agents", [])
        data.setdefault("subagent_depth", 0)
        return data

    def get_config(self):
        """Return dashboard config with defaults."""
        data = self._read_json(CONFIG_FILE)
        if not data:
            data = {
                "free_only_mode": False, "theme": "dark",
                "auto_refresh_seconds": 30, "disabled_models": [], "projects": {}
            }
            self._write_json(CONFIG_FILE, data)
        data.setdefault("disabled_models", [])
        data.setdefault("projects", {})
        return data

    def save_config(self, cfg):
        """Persist config and invalidate cache."""
        self._write_json(CONFIG_FILE, cfg)
        self.invalidate(CONFIG_FILE)

    def get_models_raw(self):
        return self._read_json(MODELS_FILE) or {"models": []}

    def save_models_raw(self, data):
        self._write_json(MODELS_FILE, data)
        self.invalidate(MODELS_FILE)

    def get_logs(self, level=None, source=None, since=None, limit=100):
        """Read JSONL log with optional filters. Returns list of dicts."""
        raw = self._read_file(JSONL_FILE, cache=False)
        if not raw:
            return []
        entries = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if level and entry.get("level", "").lower() != level.lower():
                continue
            if source and entry.get("source", "").lower() != source.lower():
                continue
            if since and entry.get("ts", "") < since:
                continue
            entries.append(entry)

        entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
        return entries[:limit]

    def get_new_logs(self, path, known_positions):
        """Tail a JSONL file and return new entries + new positions dict."""
        result_path = path
        try:
            mtime = os.path.getmtime(path)
            size = os.path.getsize(path)
            last_pos = known_positions.get(path, 0)
            known_positions[path] = size
        except OSError:
            return [], known_positions

        if size <= last_pos:
            return [], known_positions

        with open(path) as f:
            f.seek(last_pos)
            new_raw = f.read()

        entries = []
        for line in new_raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass

        return entries, known_positions

    def get_activity(self, count=50):
        """Return most recent activity entries from JSONL."""
        return self.get_logs(limit=count)

    def get_projects(self):
        """List projects with session count and last activity."""
        if not os.path.exists(PROJECTS_DIR):
            return {"projects": [], "count": 0}

        projects = []
        for name in sorted(os.listdir(PROJECTS_DIR)):
            pp = os.path.join(PROJECTS_DIR, name)
            if not os.path.isdir(pp):
                continue

            sf = os.path.join(pp, "sessions.json")
            sessions = []
            if os.path.exists(sf):
                try:
                    with open(sf) as f:
                        sessions = json.load(f).get("sessions", [])
                except (json.JSONDecodeError, IOError):
                    pass

            projects.append({
                "name": name,
                "session_count": len(sessions),
                "sessions": sessions[:5],
                "created": sessions[0].get("date", "N/A") if sessions else "N/A",
                "task_count": len(set(s.get("task", "") for s in sessions))
            })

        cfg = self.get_config()
        for p in projects:
            pc = cfg.get("projects", {}).get(p["name"], {})
            p["model_allowlist"] = pc.get("model_allowlist", [])
            p["allowlist_count"] = len(p["model_allowlist"])
            p["free_only"] = pc.get("free_only", False)
            p["location"] = pc.get("location", "")

        return {"projects": projects, "count": len(projects)}

    def get_sessions(self):
        """Parse session_log.md into structured data."""
        raw = self._read_file(SESSION_LOG_FILE)
        if not raw:
            return {"sessions": [], "count": 0, "projects": []}

        sessions = []
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("|") and not line.startswith("|---") and not line.startswith("| Date"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 5:
                    sessions.append({
                        "date": parts[0], "project": parts[1], "task": parts[2],
                        "model": parts[3],
                        "agent": parts[4] if len(parts) > 4 else "shell",
                        "status": parts[5] if len(parts) > 5 else "",
                        "duration": parts[6] if len(parts) > 6 else "",
                        "qa_done": "✓" in parts[7] if len(parts) > 7 else False,
                        "checked": "✓" in parts[8] if len(parts) > 8 else False,
                        "notes": parts[9] if len(parts) > 9 else "",
                    })

        projects = list(dict.fromkeys(s["project"] for s in sessions))
        return {"sessions": sessions, "count": len(sessions), "projects": projects}

    def get_prices(self):
        """Parse price changes log."""
        raw = self._read_file(PRICES_FILE)
        if not raw:
            return {"entries": [], "count": 0}
        entries = [
            {"text": l.strip()}
            for l in raw.split("\n")
            if l.strip() and not l.startswith("#")
        ]
        return {"entries": entries, "count": len(entries)}

    def get_agents(self):
        """Derive live agent state from state.json + sessions."""
        state = self.get_state()
        agents = []

        if state.get("agent") and state.get("project"):
            agents.append({
                "name": state["agent"],
                "model": state.get("model", "?"),
                "project": state.get("project", ""),
                "task": state.get("task", ""),
                "status": "active",
                "subagent_depth": state.get("subagent_depth", 0),
                "last_seen": state.get("timestamp", ""),
            })

        # Merge in explicitly tracked agents from state.json
        for a in state.get("agents", []):
            existing = next((x for x in agents if x["name"] == a.get("name")), None)
            if existing:
                existing.update(a)
            else:
                a.setdefault("status", "active")
                agents.append(a)

        return agents

    def _write_json(self, path, data):
        """Thread-safe JSON write."""
        with self._lock:
            with open(path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    # ── Project doc helpers ──

    def project_dir(self, name):
        pd = os.path.join(PROJECTS_DIR, name)
        os.makedirs(pd, exist_ok=True)
        return pd

    def _safe(self, name):
        return ".." not in name and "/" not in name and "\\" not in name

    def list_project_docs(self, name):
        pd = self.project_dir(name)
        files = []
        for f in sorted(os.listdir(pd)):
            fp = os.path.join(pd, f)
            if os.path.isfile(fp):
                st = os.stat(fp)
                files.append({
                    "name": f, "size": st.st_size,
                    "modified": st.st_mtime,
                    "is_md": f.endswith(".md"),
                    "is_json": f.endswith(".json"),
                })
        return files

    def read_project_doc(self, name, fn):
        if not self._safe(fn):
            return None
        fp = os.path.join(self.project_dir(name), fn)
        if not os.path.exists(fp):
            return None
        with open(fp) as f:
            return f.read()

    def write_project_doc(self, name, fn, content):
        if not self._safe(fn):
            return False
        with open(os.path.join(self.project_dir(name), fn), "w") as f:
            f.write(content)
        return True

    def delete_project_doc(self, name, fn):
        if not self._safe(fn):
            return False
        fp = os.path.join(self.project_dir(name), fn)
        if os.path.exists(fp):
            os.remove(fp)
            self.invalidate(fp)
            return True
        return False

    def get_project_state(self, name):
        pd = self.project_dir(name)
        cfg = self.get_config()
        proj_cfg = cfg.get("projects", {}).get(name, {})
        sessions = []
        sf = os.path.join(pd, "sessions.json")
        if os.path.exists(sf):
            try:
                with open(sf) as f:
                    sessions = json.load(f).get("sessions", [])
            except (json.JSONDecodeError, IOError):
                pass

        return {
            "name": name,
            "config": proj_cfg,
            "sessions": sessions,
            "session_count": len(sessions),
            "docs": self.list_project_docs(name),
            "state": self.read_project_doc(name, "STATE.md") or "",
            "roadmap": self.read_project_doc(name, "ROADMAP.md") or "",
            "context": self.read_project_doc(name, "CONTEXT.md") or "",
            "notes": self.read_project_doc(name, "NOTES.md") or "",
        }


# ────────────────────────────────────────────────────────────
# SSE Broadcaster — polls DataStore, pushes events to clients
# ────────────────────────────────────────────────────────────

class SSEBroadcaster:
    """Server-Sent Events broadcaster. Polls DataStore every 2s and pushes delta events."""

    def __init__(self, datastore):
        self._clients = []  # list of (wfile, lock)
        self._last_positions = {}  # path -> byte_offset
        self._last_state = None
        self._last_jsonl_count = 0
        self._lock = threading.Lock()
        self._ds = datastore
        self._running = False
        self._thread = None

    def add_client(self, wfile, lock):
        """Register a new SSE client."""
        with self._lock:
            self._clients.append((wfile, lock))

    def remove_client(self, wfile):
        """Unregister a client (on disconnect)."""
        with self._lock:
            self._clients = [(w, l) for w, l in self._clients if w != wfile]

    def start(self):
        """Start background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _poll_loop(self):
        """Poll every 2 seconds and broadcast deltas."""
        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                print(f"[SSE] Poll error: {e}")
            time.sleep(2)

    def _poll_once(self):
        """Check for changes and push events."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

        # ── Check state.json for context changes ──
        state = self._ds.get_state()
        state_changed = state != self._last_state
        if state_changed:
            self._broadcast("state", {
                "type": "state",
                "project": state.get("project"),
                "task": state.get("task"),
                "model": state.get("model"),
                "agent": state.get("agent"),
                "subagent_depth": state.get("subagent_depth", 0),
                "timestamp": state.get("timestamp", now),
            })
            # Also broadcast agent update
            agents = self._ds.get_agents()
            self._broadcast("agents", {
                "type": "agents",
                "agents": agents,
                "count": len(agents),
                "timestamp": now,
            })
            self._last_state = state

        # ── Check JSONL for new log lines ──
        new_entries, self._last_positions = self._ds.get_new_logs(
            JSONL_FILE, self._last_positions
        )
        if new_entries:
            new_count = len(new_entries)
            self._broadcast("activity", {
                "type": "activity",
                "events": new_entries,
                "count": new_count,
                "timestamp": now,
            })
            self._last_jsonl_count += new_count

        # ── Periodic heartbeat (every 6s = every 3rd poll) ──
        # Send heartbeat always to keep connection alive
        self._broadcast("heartbeat", {
            "type": "heartbeat",
            "ts": now,
            "server": "ok",
        })

        # ── Clean disconnected clients ──
        self._cleanup_clients()

    def _broadcast(self, event_name, data):
        """Push SSE event to all connected clients."""
        payload = f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        dead = []
        with self._lock:
            for wfile, lock in self._clients:
                try:
                    with lock:
                        wfile.write(payload.encode())
                        wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    dead.append(wfile)

        for w in dead:
            self.remove_client(w)

    def _cleanup_clients(self):
        """Remove clients whose connections are dead."""
        with self._lock:
            alive = []
            for wfile, lock in self._clients:
                try:
                    with lock:
                        wfile.write(b": keepalive\n\n")
                        wfile.flush()
                    alive.append((wfile, lock))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            self._clients = alive


# ────────────────────────────────────────────────────────────
# Model helpers (kept from v3)
# ────────────────────────────────────────────────────────────

def model_is_paid(m):
    ct = m.get("cost", {}).get("type", "")
    return ct in ("subscription", "payg", "pay_per_token")


def model_is_disabled(m_id, cfg):
    return m_id in cfg.get("disabled_models", [])


def filter_models_by_config(models, cfg, project=None):
    result = list(models)
    if cfg.get("free_only_mode"):
        result = [m for m in result if not model_is_paid(m)]
    disabled = cfg.get("disabled_models", [])
    if disabled:
        result = [m for m in result if m.get("id") not in disabled]
    if project:
        proj_cfg = cfg.get("projects", {}).get(project, {})
        wl = proj_cfg.get("model_allowlist", [])
        if wl:
            result = [m for m in result if m.get("id") in wl]
        if proj_cfg.get("free_only"):
            result = [m for m in result if not model_is_paid(m)]
    return result


def model_summary(m):
    return {
        "id": m.get("id", "?"),
        "name": m.get("name", m.get("id", "?")),
        "provider": m.get("provider", m.get("host", "?")),
        "tier": m.get("tier", 0),
        "speed_rating": m.get("speed_rating", 0),
        "context_window": m.get("context_window", 0),
        "architecture": m.get("architecture", ""),
        "status": m.get("status", "active"),
        "agent_ready": m.get("agent_ready", True),
        "cost_type": m.get("cost", {}).get("type", "?"),
        "cost_amount": m.get("cost", {}).get("amount", 0),
        "cost_period": m.get("cost", {}).get("period", ""),
        "cost_limits": m.get("cost", {}).get("limits", ""),
        "cost_source": m.get("cost", {}).get("source_url", ""),
        "cost_last_checked": m.get("cost", {}).get("last_checked", ""),
        "capabilities": m.get("capabilities", {}),
        "user_notes": m.get("user_notes", ""),
        "research_notes": m.get("research_notes", ""),
        "research_sources": m.get("research_sources", []),
        "catalogued_by": m.get("catalogued_by", ""),
        "last_tested": m.get("last_tested", ""),
        "gpu": m.get("gpu", ""),
    }


# ────────────────────────────────────────────────────────────
# HTTP Request Handler
# ────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    """HTTP handler with all dashboard API routes."""

    # Shared across instances
    ds = DataStore()
    broadcaster = SSEBroadcaster(ds)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        cfg = self.ds.get_config()

        # ── Serve HTML ──
        if path in ("/", "/index.html"):
            self._serve_file("text/html")
            return

        # ── SSE Stream ──
        if path == "/api/activity/stream":
            self._handle_sse()
            return

        # ── Models ──
        if path == "/api/models":
            self._handle_get_models(qs, cfg)
            return

        # ── Sessions ──
        if path == "/api/sessions":
            self._json(self.ds.get_sessions())
            return

        # ── Prices ──
        if path == "/api/prices":
            self._json(self.ds.get_prices())
            return

        # ── Projects ──
        if path == "/api/projects":
            self._json(self.ds.get_projects())
            return

        # ── Project state ──
        if path == "/api/project-state":
            name = qs.get("name", [None])[0]
            if not name:
                self._error(400, "Missing name")
                return
            self._json(self.ds.get_project_state(name))
            return

        # ── Project doc ──
        if path == "/api/project-doc":
            name = qs.get("name", [None])[0]
            fn = qs.get("file", [None])[0]
            if not name or not fn:
                self._error(400, "Missing name or file")
                return
            content = self.ds.read_project_doc(name, fn)
            if content is None:
                self._error(404, "Not found")
                return
            self._json({"content": content, "name": name, "file": fn})
            return

        # ── Activity feed ──
        if path == "/api/activity":
            limit = int(qs.get("limit", [50])[0])
            level = qs.get("level", [None])[0]
            source = qs.get("source", [None])[0]
            self._json({
                "events": self.ds.get_activity(limit=limit),
                "count": 0,
                "level": level,
                "source": source,
            })
            return

        # ── Agents ──
        if path == "/api/agents":
            self._json({
                "agents": self.ds.get_agents(),
                "count": len(self.ds.get_agents()),
            })
            return

        # ── State ──
        if path == "/api/state":
            self._json(self.ds.get_state())
            return

        # ── Status ──
        if path == "/api/status":
            pl = os.path.exists(PRICES_FILE)
            self._json({
                "nightly_price_check": "Configured (2 AM)" if pl else "Not configured",
                "price_log_exists": pl,
                "data_dir": DATA_DIR,
                "free_only_mode": cfg.get("free_only_mode", False),
                "disabled_models": len(cfg.get("disabled_models", [])),
                "projects_configured": len(cfg.get("projects", {})),
                "server_version": "v4",
            })
            return

        # ── Config ──
        if path == "/api/config":
            self._json(cfg)
            return

        # ── All (aggregate) ──
        if path == "/api/all":
            projects = self.ds.get_projects()
            self._json({
                "sessions": self.ds.get_sessions(),
                "models": self._load_filtered_models(cfg),
                "prices": self.ds.get_prices(),
                "projects": projects,
                "config": cfg,
                "agents": self.ds.get_agents(),
                "state": self.ds.get_state(),
                "status": {
                    "nightly_price_check": "Configured (2 AM)",
                    "price_log_exists": os.path.exists(PRICES_FILE),
                    "data_dir": DATA_DIR,
                    "free_only_mode": cfg.get("free_only_mode", False),
                    "disabled_models": len(cfg.get("disabled_models", [])),
                    "projects_configured": len(cfg.get("projects", {})),
                    "server_version": "v4",
                },
            })
            return

        self._error(404, "Not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        cl = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(cl)

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._error(400, "Invalid JSON")
            return

        # ── Project doc write ──
        if path == "/api/project-doc":
            name = data.get("name")
            fn = data.get("file")
            content = data.get("content", "")
            if not name or not fn:
                self._error(400, "Missing name or file")
                return
            if self.ds.write_project_doc(name, fn, content):
                self.ds.invalidate_all()
                self._json({"ok": True, "action": "saved", "name": name, "file": fn})
            else:
                self._error(400, "Invalid filename")
            return

        # ── Project state ──
        if path == "/api/project-state":
            name = data.get("name")
            if not name:
                self._error(400, "Missing name")
                return
            self.ds.project_dir(name)
            if "config" in data:
                cfg = self.ds.get_config()
                cfg.setdefault("projects", {})
                cfg["projects"].setdefault(name, {})
                cfg["projects"][name].update(data["config"])
                self.ds.save_config(cfg)
            self._json({"ok": True, "action": "created", "name": name})
            return

        # ── Config update ──
        if path == "/api/config":
            cfg = self.ds.get_config()
            for key in ("free_only_mode", "theme", "auto_refresh_seconds", "disabled_models"):
                if key in data:
                    cfg[key] = data[key]
            if "projects" in data and isinstance(data["projects"], dict):
                for pn, pc in data["projects"].items():
                    cfg["projects"].setdefault(pn, {"model_allowlist": [], "free_only": False})
                    if "model_allowlist" in pc:
                        cfg["projects"][pn]["model_allowlist"] = pc["model_allowlist"]
                    if "free_only" in pc:
                        cfg["projects"][pn]["free_only"] = pc["free_only"]
                    if "location" in pc:
                        cfg["projects"][pn]["location"] = pc["location"]
            self.ds.save_config(cfg)
            self.ds.invalidate_all()
            self._json({"ok": True, "config": cfg})
            return

        # ── Model create/update ──
        if path == "/api/models":
            model_id = data.get("id")
            if not model_id:
                self._error(400, "Missing id")
                return
            mdata = self.ds.get_models_raw()
            found_idx = None
            for i, m in enumerate(mdata.get("models", [])):
                if m.get("id") == model_id:
                    found_idx = i
                    break
            if found_idx is not None:
                existing = mdata["models"][found_idx]
                for key, val in data.items():
                    if key == "cost" and isinstance(val, dict) and isinstance(existing.get("cost"), dict):
                        existing["cost"].update(val)
                    elif key == "capabilities" and isinstance(val, dict) and isinstance(existing.get("capabilities"), dict):
                        existing["capabilities"].update(val)
                    else:
                        existing[key] = val
                mdata["models"][found_idx] = existing
                self.ds.save_models_raw(mdata)
                ms = model_summary(existing)
                ms["disabled"] = model_is_disabled(existing["id"], self.ds.get_config())
                self._json({"ok": True, "action": "updated", "model": ms})
            else:
                mdata.setdefault("models", []).append(data)
                self.ds.save_models_raw(mdata)
                ms = model_summary(data)
                ms["disabled"] = model_is_disabled(data.get("id", ""), self.ds.get_config())
                self._json({"ok": True, "action": "created", "model": ms})
            self.ds.invalidate(MODELS_FILE)
            return

        self._error(404, "Not found")

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/models" and "id" in qs:
            mid = qs["id"][0]
            data = self.ds.get_models_raw()
            orig = len(data.get("models", []))
            data["models"] = [m for m in data.get("models", []) if m.get("id") != mid]
            if len(data["models"]) < orig:
                self.ds.save_models_raw(data)
                self.ds.invalidate(MODELS_FILE)
                self._json({"ok": True, "action": "deleted", "id": mid})
            else:
                self._error(404, "Not found")
            return

        if path == "/api/project-doc":
            name = qs.get("name", [None])[0]
            fn = qs.get("file", [None])[0]
            if not name or not fn:
                self._error(400, "Missing name or file")
                return
            if self.ds.delete_project_doc(name, fn):
                self._json({"ok": True, "action": "deleted", "name": name, "file": fn})
            else:
                self._error(404, "Not found or invalid")
            return

        self._error(404, "Not found")

    def do_OPTIONS(self):
        self._cors_headers()
        self.send_response(200)
        self.end_headers()

    # ── Internal helper methods ──

    def _handle_sse(self):
        """Establish SSE connection and keep it open."""
        self.send_response(200)
        self._cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        # Register this client
        wfile = self.wfile
        lock = threading.Lock()
        self.broadcaster.add_client(wfile, lock)

        # Ensure broadcaster is running
        self.broadcaster.start()

        try:
            while True:
                time.sleep(30)
                with lock:
                    try:
                        wfile.write(b": keepalive\n\n")
                        wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.broadcaster.remove_client(wfile)

    def _handle_get_models(self, qs, cfg):
        data = self.ds.get_models_raw()
        project = qs.get("project", [None])[0]

        if "id" in qs:
            mid = qs["id"][0]
            for m in data.get("models", []):
                if m.get("id") == mid:
                    ms = model_summary(m)
                    ms["disabled"] = model_is_disabled(m["id"], cfg)
                    self._json(ms)
                    return
            self._error(404, "Model not found")
            return

        if "all" in qs:
            all_m = [model_summary(m) for m in data.get("models", [])]
            for m in all_m:
                m["disabled"] = model_is_disabled(m["id"], cfg)
            self._json({"models": all_m, "total": len(all_m)})
            return

        # Filtered view
        self._json(self._load_filtered_models(cfg, project))

    def _load_filtered_models(self, cfg, project=None):
        data = self.ds.get_models_raw()
        filtered = filter_models_by_config(data.get("models", []), cfg, project)
        models = [model_summary(m) for m in filtered]
        active = sum(1 for m in models if m["agent_ready"] and m["status"] != "removed")
        broken = sum(1 for m in models if not m["agent_ready"])
        removed = sum(1 for m in models if m["status"] == "removed")
        return {
            "models": models,
            "total": len(models),
            "active": active,
            "broken": broken,
            "removed": removed,
            "free_only": cfg.get("free_only_mode", False),
            "disabled_count": len(cfg.get("disabled_models", [])),
            "project": project,
        }

    def _serve_file(self, ct):
        p = os.path.join(os.path.dirname(__file__), "index.html")
        if not os.path.exists(p):
            # Fallback: inline minimal
            self._error(404, "index.html not found")
            return
        with open(p) as f:
            c = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self._cors_headers()
        self.end_headers()
        self.wfile.write(c.encode())

    def _json(self, d):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(d, indent=2, ensure_ascii=False).encode())

    def _error(self, code, message):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *a):
        print(f"[Dash v4] {a[0]} {a[1]} {a[2]}")


# ────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"╔══ Dashboard v4 ═══════════════════════════════════╗")
    print(f"║  Port: {PORT} (v3 on 8766)                          ║")
    print(f"║  Data: {DATA_DIR}                   ║")
    print(f"║  SSE:  /api/activity/stream                      ║")
    print(f"║  UI:   http://localhost:{PORT}                      ║")
    print(f"╚═══════════════════════════════════════════════════╝")

    # Start broadcaster
    Handler.broadcaster.start()

    s = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        Handler.broadcaster.stop()
        s.server_close()
