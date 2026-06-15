#!/usr/bin/env python3
"""Orchestration Dashboard v3 — model CRUD, project docs, session tracking, price monitoring."""

import json, os, http.server, urllib.parse, time, threading
from datetime import datetime, timezone
import urllib.request

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("ORCHESTRATOR_DATA_DIR",
                          os.path.join(os.path.dirname(os.path.dirname(SKILL_DIR)), "orchestrator-data"))
PORT = int(os.environ.get("DASHBOARD_PORT", "8767"))
MODELS_FILE = os.path.join(DATA_DIR, "models.json")
CONFIG_FILE = os.path.join(DATA_DIR, "dashboard-config.json")

# ── Gateway Token ────────────────────────────────────────────────
GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 18789

def _read_gateway_token():
    """Read gateway auth token from openclaw.json"""
    try:
        p = os.path.join(os.environ.get("HOME", "/home/genorbox1"), ".openclaw", "openclaw.json")
        with open(p) as f:
            cfg = json.load(f)
        t = cfg.get("gateway", {}).get("auth", {}).get("token", "")
        if t and "REDACTED" not in t and not t.startswith("__"):
            return t
    except:
        pass
    return os.environ.get("GATEWAY_TOKEN", "")

GATEWAY_TOKEN = _read_gateway_token()
if not GATEWAY_TOKEN:
    print("[Dash] WARNING: No GATEWAY_TOKEN — chat/send won't work")

# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def read_file(path):
    if not os.path.exists(path): return None
    with open(path) as f: return f.read()

def load_config():
    content = read_file(CONFIG_FILE)
    if not content:
        default = {"free_only_mode": False, "theme": "dark", "auto_refresh_seconds": 30,
                   "disabled_models": [], "projects": {}}
        save_config(default)
        return default
    cfg = json.loads(content)
    cfg.setdefault("disabled_models", [])
    cfg.setdefault("projects", {})
    return cfg

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def model_is_paid(m):
    return m.get("cost", {}).get("type", "") in ("subscription", "payg", "pay_per_token")

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
        "id": m.get("id", "?"), "name": m.get("name", m.get("id", "?")),
        "provider": m.get("provider", m.get("host", "?")),
        "tier": m.get("tier", 0), "speed_rating": m.get("speed_rating", 0),
        "context_window": m.get("context_window", 0), "architecture": m.get("architecture", ""),
        "status": m.get("status", "active"), "agent_ready": m.get("agent_ready", True),
        "cost_type": m.get("cost", {}).get("type", "?"),
        "cost_amount": m.get("cost", {}).get("amount", 0),
        "cost_period": m.get("cost", {}).get("period", ""),
        "cost_limits": m.get("cost", {}).get("limits", ""),
        "cost_source": m.get("cost", {}).get("source_url", ""),
        "cost_last_checked": m.get("cost", {}).get("last_checked", ""),
        "capabilities": m.get("capabilities", {}), "user_notes": m.get("user_notes", ""),
        "research_notes": m.get("research_notes", ""),
        "research_sources": m.get("research_sources", []),
        "catalogued_by": m.get("catalogued_by", ""),
        "last_tested": m.get("last_tested", ""), "gpu": m.get("gpu", ""),
    }

# ── Project Doc CRUD ──────────────────────────────────────

def project_dir(name):
    pd = os.path.join(DATA_DIR, "projects", name)
    os.makedirs(pd, exist_ok=True)
    return pd

def _safe(name):
    return ".." not in name and "/" not in name and "\\" not in name

def datetime_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now().microsecond // 1000:03d}Z"

def write_action(data_dir, action):
    """Write a control action file for the plugin to pick up."""
    cd = os.path.join(data_dir, "control")
    os.makedirs(cd, exist_ok=True)
    fp = os.path.join(cd, action["id"] + ".action.json")
    with open(fp, "w") as f:
        json.dump(action, f, indent=2, ensure_ascii=False)

def list_project_docs(name):
    pd = project_dir(name)
    files = []
    for f in sorted(os.listdir(pd)):
        fp = os.path.join(pd, f)
        if os.path.isfile(fp):
            st = os.stat(fp)
            files.append({"name": f, "size": st.st_size, "modified": st.st_mtime,
                          "is_md": f.endswith(".md"), "is_json": f.endswith(".json")})
    return files

def read_project_doc(name, fn):
    if not _safe(fn): return None
    fp = os.path.join(project_dir(name), fn)
    if not os.path.exists(fp): return None
    with open(fp) as f: return f.read()

def write_project_doc(name, fn, content):
    if not _safe(fn): return False
    with open(os.path.join(project_dir(name), fn), "w") as f: f.write(content)
    return True

def delete_project_doc(name, fn):
    if not _safe(fn): return False
    fp = os.path.join(project_dir(name), fn)
    if os.path.exists(fp): os.remove(fp); return True
    return False

def get_project_state(name):
    pd = project_dir(name)
    cfg = load_config()
    proj_cfg = cfg.get("projects", {}).get(name, {})
    sessions = []
    sf = os.path.join(pd, "sessions.json")
    if os.path.exists(sf):
        try:
            with open(sf) as f: sessions = json.load(f).get("sessions", [])
        except: pass
    
    # Find live sessions MATCHED to this project
    matched_live = []
    agent_on_project = False
    agents_active = 0
    name_lower = name.lower()
    
    live_file = os.path.join(DATA_DIR, "live-sessions.json")
    if os.path.exists(live_file):
        try:
            with open(live_file) as f:
                live = json.load(f)
            for s in live.get("sessions", []):
                sk = s.get("key", "").lower()
                dn = s.get("displayName", "").lower()
                # Match — project name in session key or display name
                # Also match common agent patterns (main, spice, etc assigned to this project)
                if name_lower in sk or name_lower in dn:
                    matched_live.append({
                        "key": s.get("key", ""),
                        "displayName": s.get("displayName", ""),
                        "model": s.get("model", ""),
                        "status": s.get("status", "idle"),
                        "messages": len(s.get("messages", [])),
                        "live": True,
                    })
        except:
            pass
    
    # Also check live-agents.json for agents currently working on this project
    la_file = os.path.join(DATA_DIR, "live-agents.json")
    if os.path.exists(la_file):
        try:
            with open(la_file) as f:
                la = json.load(f)
            for a in la.get("agents", []):
                ap = (a.get("project") or "").lower()
                if ap and (ap == name_lower or name_lower in ap or ap in name_lower):
                    agent_on_project = True
                    agents_active += 1
                    # Also add as a matched live session if not already there
                    if not any(m.get("key","") == a.get("session_key","") for m in matched_live):
                        matched_live.append({
                            "key": a.get("session_key", ""),
                            "displayName": a.get("agent", "Unknown"),
                            "model": a.get("model", ""),
                            "status": a.get("agent_status", "idle"),
                            "messages": 0,
                            "live": True,
                        })
        except:
            pass
    
    # Include all live sessions on gateway as "available" for reference
    total_gateway = 0
    if os.path.exists(live_file):
        try:
            with open(live_file) as f:
                live = json.load(f)
            total_gateway = live.get("_meta", {}).get("sessionCount", 0)
        except:
            pass
    
    return {
        "name": name, "config": proj_cfg, "sessions": sessions,
        "session_count": len(sessions), "docs": list_project_docs(name),
        "state": read_project_doc(name, "STATE.md") or "",
        "roadmap": read_project_doc(name, "ROADMAP.md") or "",
        "context": read_project_doc(name, "CONTEXT.md") or "",
        "notes": read_project_doc(name, "NOTES.md") or "",
        "matched_live": matched_live,
        "live_matched_count": len(matched_live),
        "agent_on_project": agent_on_project,
        "agents_active": agents_active,
        "total_gateway": total_gateway,
    }

# ═══════════════════════════════════════════════════════════
# DATA LOADERS
# ═══════════════════════════════════════════════════════════

def load_models_raw():
    c = read_file(MODELS_FILE)
    return json.loads(c) if c else {"models": []}

def save_models_raw(data):
    with open(MODELS_FILE, "w") as f: json.dump(data, f, indent=2, ensure_ascii=False)

def load_models(project=None):
    data = load_models_raw()
    cfg = load_config()
    filtered = filter_models_by_config(data.get("models", []), cfg, project)
    models = [model_summary(m) for m in filtered]
    active = sum(1 for m in models if m["agent_ready"] and m["status"] != "removed")
    broken = sum(1 for m in models if not m["agent_ready"])
    removed = sum(1 for m in models if m["status"] == "removed")
    return {"models": models, "total": len(models), "active": active, "broken": broken,
            "removed": removed, "free_only": cfg.get("free_only_mode", False),
            "disabled_count": len(cfg.get("disabled_models", [])), "project": project}

def parse_session_log():
    c = read_file(os.path.join(DATA_DIR, "session_log.md"))
    if not c: return {"sessions": [], "count": 0, "projects": []}
    sessions = []
    for line in c.split("\n"):
        line = line.strip()
        if line.startswith("|") and not line.startswith("|---") and not line.startswith("| Date"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 5:
                sessions.append({"date": parts[0], "project": parts[1], "task": parts[2],
                    "model": parts[3], "agent": parts[4] if len(parts) > 4 else "shell",
                    "status": parts[5] if len(parts) > 5 else "",
                    "duration": parts[6] if len(parts) > 6 else "",
                    "qa_done": "✓" in parts[7] if len(parts) > 7 else False,
                    "checked": "✓" in parts[8] if len(parts) > 8 else False,
                    "notes": parts[9] if len(parts) > 9 else ""})
    projects = list(dict.fromkeys(s["project"] for s in sessions))
    return {"sessions": sessions, "count": len(sessions), "projects": projects}

def parse_price_log():
    c = read_file(os.path.join(DATA_DIR, "price_changes.log"))
    if not c: return {"entries": [], "count": 0}
    entries = [{"text": l.strip()} for l in c.split("\n") if l.strip() and not l.startswith("#")]
    return {"entries": entries, "count": len(entries)}

def load_projects():
    pd = os.path.join(DATA_DIR, "projects")
    if not os.path.exists(pd): return {"projects": [], "count": 0}
    
    # Load live sessions from bridge data
    live_sessions = []
    live_file = os.path.join(DATA_DIR, "live-sessions.json")
    if os.path.exists(live_file):
        try:
            with open(live_file) as f:
                live = json.load(f)
            live_sessions = live.get("sessions", [])
        except:
            pass
    
    projects = []
    for name in sorted(os.listdir(pd)):
        pp = os.path.join(pd, name)
        if not os.path.isdir(pp): continue
        sf = os.path.join(pp, "sessions.json")
        sessions = []
        if os.path.exists(sf):
            try:
                with open(sf) as f: sessions = json.load(f).get("sessions", [])
            except: pass
        
        # Try matching live sessions by agent key containing project name fragment
        agent_match = [s for s in live_sessions 
            if s.get("key","").startswith(f"agent:{name}") or 
               s.get("displayName","").lower() == name.lower()]
        
        task_ct = len(set(s.get("task","") for s in sessions))
        
        projects.append({
            "name": name,
            "session_count": len(sessions),
            "sessions": sessions[:5],
            "created": sessions[0].get("logged_at", sessions[0].get("timestamp", "N/A")) if sessions else "N/A",
            "task_count": task_ct,
            "live_count": len(agent_match),
        })
    return {"projects": projects, "count": len(projects)}

def enrich_projects(projects_data, cfg):
    for p in projects_data.get("projects", []):
        pc = cfg.get("projects", {}).get(p["name"], {})
        p["model_allowlist"] = pc.get("model_allowlist", [])
        p["allowlist_count"] = len(p["model_allowlist"])
        p["free_only"] = pc.get("free_only", False)
    return projects_data

# ═══════════════════════════════════════════════════════════
# HTTP HANDLER
# ═══════════════════════════════════════════════════════════

class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        cfg = load_config()

        if path in ("/", "/index.html"):
            self.serve_file("index.html", "text/html")

        elif path == "/api/models":
            data = load_models_raw()
            project = qs.get("project", [None])[0]
            if "id" in qs:
                mid = qs["id"][0]
                for m in data.get("models", []):
                    if m.get("id") == mid:
                        ms = model_summary(m); ms["disabled"] = model_is_disabled(m["id"], cfg)
                        return self.send_json(ms)
                return self.send_error(404, json.dumps({"error": "Model not found"}))
            elif "all" in qs:
                all_m = [model_summary(m) for m in data.get("models", [])]
                for m in all_m: m["disabled"] = model_is_disabled(m["id"], cfg)
                return self.send_json({"models": all_m, "total": len(all_m)})
            else:
                return self.send_json(load_models(project=project))

        elif path == "/api/sessions":
            # Live data from bridge, fallback to markdown log
            live_file = os.path.join(DATA_DIR, "live-sessions.json")
            if os.path.exists(live_file):
                try:
                    with open(live_file) as f:
                        live = json.load(f)
                    self.send_json({"live": True, "session_count": live["_meta"]["sessionCount"],
                        "sessions": live["sessions"], "updated": live["_meta"]["updatedAt"]})
                    return
                except Exception as e:
                    pass
            # Fallback to markdown log
            self.send_json(parse_session_log())

        elif path == "/api/logs":
            # Proxy to orchestrator_get_logs via gateway
            log_limit = int(qs.get("limit", ["50"])[0])
            log_level = qs.get("level", [None])[0]
            log_args = {"limit": log_limit}
            if log_level: log_args["level"] = log_level
            orc_logs = self._gateway_invoke("orchestrator_get_logs", log_args)
            if orc_logs.get("ok"):
                try:
                    text_payload = orc_logs["result"]["content"][0]["text"]
                    payload = json.loads(text_payload)
                    entries = payload.get("entries", [])
                    sources = sorted(set(e.get("source", "?") for e in entries))
                    source_counts = {}
                    for s in sources: source_counts[s] = sum(1 for e in entries if e.get("source", "?") == s)
                    self.send_json({"ok": True, "entries": entries, "count": len(entries),
                        "sources": sources,
                        "source_counts": [{k: v} for k, v in sorted(source_counts.items(), key=lambda x: -x[1])]})
                except Exception as e:
                    self.send_json({"ok": False, "error": f"Parse: {e}"})
            else:
                self.send_json({"ok": False, "error": "No orchestrator logs available"})

        elif path == "/api/prices":
            self.send_json(parse_price_log())

        elif path == "/api/projects":
            result = load_projects()
            self.send_json(enrich_projects(result, cfg))

        elif path == "/api/project-state":
            name = qs.get("name", [None])[0]
            if not name: return self.send_error(400, json.dumps({"error": "Missing name"}))
            self.send_json(get_project_state(name))

        elif path == "/api/project-doc":
            name = qs.get("name", [None])[0]
            fn = qs.get("file", [None])[0]
            if not name or not fn: return self.send_error(400, json.dumps({"error": "Missing name or file"}))
            content = read_project_doc(name, fn)
            if content is None: return self.send_error(404, json.dumps({"error": "Not found"}))
            self.send_json({"content": content, "name": name, "file": fn})

        elif path == "/api/status":
            pl = os.path.exists(os.path.join(DATA_DIR, "price_changes.log"))
            self.send_json({"nightly_price_check": "Configured (2 AM)" if pl else "Not configured",
                "price_log_exists": pl, "data_dir": DATA_DIR,
                "free_only_mode": cfg.get("free_only_mode", False),
                "disabled_models": len(cfg.get("disabled_models", [])),
                "projects_configured": len(cfg.get("projects", {}))})

        elif path == "/api/live-agents":
            la = os.path.join(DATA_DIR, "live-agents.json")
            if os.path.exists(la):
                with open(la) as f: self.send_json(json.load(f))
            else:
                self.send_json({"agents": [], "agent_count": 0, "active_count": 0, "message": "No live agents — plugin hooks not yet triggered"})

        elif path == "/api/session-files":
            sd = os.path.join(DATA_DIR, "sessions")
            if not os.path.exists(sd):
                return self.send_json({"files": [], "count": 0})
            files = []
            for f in sorted(os.listdir(sd), reverse=True):
                fp = os.path.join(sd, f)
                if f.endswith(".md") and os.path.isfile(fp):
                    with open(fp) as fh: content = fh.read()
                    files.append({"name": f, "content": content, "size": len(content)})
            self.send_json({"files": files, "count": len(files)})

        elif path == "/api/safeguard-log":
            sl = os.path.join(DATA_DIR, "safeguard-log.md")
            if os.path.exists(sl):
                with open(sl) as f:
                    lines = [l.strip() for l in f.readlines() if l.startswith("|") and "---" not in l]
                    entries = []
                    for l in lines[1:]:  # skip header
                        parts = [p.strip() for p in l.split("|")[1:-1]]
                        if len(parts) >= 3:
                            entries.append({"timestamp": parts[0], "event": parts[1], "details": parts[2]})
                    self.send_json({"entries": entries, "count": len(entries)})
            else:
                self.send_json({"entries": [], "count": 0, "message": "No safeguard events yet"})

        elif path == "/api/config":
            self.send_json(cfg)

        elif path == "/api/sse/live-sessions":
            self._handle_sse_live()

        elif path == "/api/all":
            projects = load_projects()
            projects = enrich_projects(projects, cfg)
            # Live session data from bridge
            live_sessions_data = {"sessions": parse_session_log(), "live_session_count": 0}
            live_file = os.path.join(DATA_DIR, "live-sessions.json")
            if os.path.exists(live_file):
                try:
                    with open(live_file) as f:
                        live = json.load(f)
                    live_sessions_data = {"sessions": live["sessions"], "live_session_count": live["_meta"]["sessionCount"],
                        "live_connected": live["_meta"]["connected"], "live_updated": live["_meta"]["updatedAt"]}
                except:
                    pass
            # Load live_agents data for dashboard state
            la_data = {"agents": [], "agent_count": 0, "active_count": 0}
            la_file = os.path.join(DATA_DIR, "live-agents.json")
            if os.path.exists(la_file):
                try:
                    with open(la_file) as f:
                        la_data = json.load(f)
                except:
                    pass
            self.send_json({**live_sessions_data, "live_agents": la_data, "state": (la_data.get("agents") or [None])[0] or {},
                "models": load_models(), "prices": parse_price_log(), "projects": projects, "config": cfg,
                "status": {"nightly_price_check": "Configured (2 AM)",
                    "price_log_exists": os.path.exists(os.path.join(DATA_DIR, "price_changes.log")),
                    "data_dir": DATA_DIR, "free_only_mode": cfg.get("free_only_mode", False),
                    "disabled_models": len(cfg.get("disabled_models", [])),
                    "projects_configured": len(cfg.get("projects", {}))}})
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        cl = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(cl)

        try: data = json.loads(body)
        except: return self.send_error(400, json.dumps({"error": "Invalid JSON"}))

        # ── Control Plane Actions ───────────────────────────
        if path == "/api/control/set-context":
            project = data.get("project")
            task = data.get("task", "")
            if not project: return self.send_error(400, json.dumps({"error": "Missing project"}))
            action_id = "set_context_" + str(int(time.time() * 1000))
            action = {"id": action_id, "action": "set_context",
                      "params": {"project": project, "task": task},
                      "created_at": datetime_now_iso(), "ttl_seconds": 30}
            write_action(DATA_DIR, action)
            self.send_json({"ok": True, "action_id": action_id, "message": "Context set request queued"})

        elif path == "/api/control/clear-context":
            action_id = "clear_context_" + str(int(time.time() * 1000))
            action = {"id": action_id, "action": "clear_context",
                      "params": {}, "created_at": datetime_now_iso(), "ttl_seconds": 30}
            write_action(DATA_DIR, action)
            self.send_json({"ok": True, "action_id": action_id, "message": "Clear context request queued"})

        elif path == "/api/control/routing":
            action_id = "routing_" + str(int(time.time() * 1000))
            params = {}
            if "free_only_mode" in data: params["free_only_mode"] = data["free_only_mode"]
            if "disabled_models" in data: params["disabled_models"] = data["disabled_models"]
            if "project" in data:
                params["project"] = data["project"]
                if "project_allowlist" in data: params["project_allowlist"] = data["project_allowlist"]
                if "project_free_only" in data: params["project_free_only"] = data["project_free_only"]
            action = {"id": action_id, "action": "update_routing",
                      "params": params, "created_at": datetime_now_iso(), "ttl_seconds": 30}
            write_action(DATA_DIR, action)
            self.send_json({"ok": True, "action_id": action_id, "message": "Routing update queued"})

        elif path == "/api/control/spawn-agent":
            action_id = "spawn_" + str(int(time.time() * 1000))
            params = {"task": data.get("task", ""), "project": data.get("project", "")}
            action = {"id": action_id, "action": "spawn_agent",
                      "params": params, "created_at": datetime_now_iso(), "ttl_seconds": 60}
            write_action(DATA_DIR, action)
            self.send_json({"ok": True, "action_id": action_id, "message": "Spawn request queued"})

        elif path == "/api/control/stop-agent":
            action_id = "stop_" + str(int(time.time() * 1000))
            params = {"agent": data.get("agent", "")}
            action = {"id": action_id, "action": "stop_agent",
                      "params": params, "created_at": datetime_now_iso(), "ttl_seconds": 60}
            write_action(DATA_DIR, action)
            self.send_json({"ok": True, "action_id": action_id, "message": "Stop request queued"})

        elif path == "/api/control/poll-result":
            action_id = data.get("action_id")
            if not action_id: return self.send_error(400, json.dumps({"error": "Missing action_id"}))
            rf = os.path.join(DATA_DIR, "control", action_id + ".result.json")
            if os.path.exists(rf):
                with open(rf) as f: result = json.load(f)
                self.send_json(result)
            else:
                self.send_json({"id": action_id, "ok": None, "result": None,
                                "error": "Not yet processed", "processed_at": None})

        # ── Existing endpoints ───────────────────────────────
        elif path == "/api/project-doc":
            name = data.get("name"); fn = data.get("file"); content = data.get("content", "")
            if not name or not fn: return self.send_error(400, json.dumps({"error": "Missing name or file"}))
            if write_project_doc(name, fn, content):
                self.send_json({"ok": True, "action": "saved", "name": name, "file": fn})
            else:
                self.send_error(400, json.dumps({"error": "Invalid filename"}))

        elif path == "/api/project-state":
            name = data.get("name")
            if not name: return self.send_error(400, json.dumps({"error": "Missing name"}))
            project_dir(name)
            if "config" in data:
                cfg = load_config()
                cfg.setdefault("projects", {})
                cfg["projects"].setdefault(name, {})
                cfg["projects"][name].update(data["config"])
                save_config(cfg)
            self.send_json({"ok": True, "action": "created", "name": name})

        elif path == "/api/chat/send":
            sk = data.get("sessionKey")
            msg = data.get("message")
            if not sk or not msg:
                return self.send_error(400, json.dumps({"error": "Missing sessionKey or message"}))
            # Write to outbox — bridge processes it asynchronously
            outbox_path = os.path.join(DATA_DIR, "chat-outbox.json")
            outbox = {"pending": []}
            try:
                with open(outbox_path) as f:
                    outbox = json.load(f)
            except:
                pass
            outbox["pending"].append({
                "id": str(time.time_ns()),
                "sessionKey": sk,
                "message": msg,
                "sent": False,
                "error": None,
                "ts": time.time()
            })
            with open(outbox_path, "w") as f:
                json.dump(outbox, f, indent=2)
            self.send_json({"ok": True, "queued": True})
            return

        elif path == "/api/chat/history":
            sk = data.get("sessionKey")
            if not sk:
                return self.send_error(400, json.dumps({"error": "Missing sessionKey"}))
            result = self._gateway_invoke("sessions_history", {"sessionKey": sk, "limit": 50, "includeTools": True})
            # Gateway returns content[0].text as a JSON string with messages
            if result.get("ok"):
                content = result.get("result", {}).get("content", [])
                text_payload = content[0]["text"] if content and "text" in content[0] else "{}"
                try:
                    payload = json.loads(text_payload)
                    msgs = payload.get("messages", [])
                    # Simplify: flatten content arrays to text, remove tool calls
                    simplified = []
                    for m in msgs:
                        role = m.get("role", "")
                        raw = m.get("content", [])
                        if isinstance(raw, list):
                            parts = []
                            for c in raw:
                                if isinstance(c, dict):
                                    if c.get("type") == "text":
                                        parts.append(c.get("text", ""))
                                    elif c.get("type") == "thinking":
                                        parts.append(f"[thinking: {c.get('thinking','')[:100]}]")
                                elif isinstance(c, str):
                                    parts.append(c)
                            text = "\n".join(p for p in parts if p)
                        else:
                            text = str(raw or "")
                        simplified.append({
                            "role": role,
                            "content": text,
                            "ts": m.get("timestamp") or m.get("ts") or 0
                        })
                    self.send_json({"ok": True, "messages": simplified})
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    self.send_json({"ok": False, "error": f"Parse error: {e}"})
            else:
                self.send_json({"ok": False, "error": result.get("error", "Failed")})
            return

        elif path == "/api/config":
            cfg = load_config()
            for key in ("free_only_mode", "theme", "auto_refresh_seconds", "disabled_models"):
                if key in data: cfg[key] = data[key]
            if "safeguards" in data and isinstance(data["safeguards"], dict):
                cfg_sg = cfg.setdefault("safeguards", {})
                for sk in ("enabled", "idle_timeout_ms", "stuck_timeout_ms", "max_errors_before_escalation", "auto_recover", "tick_interval_ms"):
                    if sk in data["safeguards"]: cfg_sg[sk] = data["safeguards"][sk]
            if "projects" in data and isinstance(data["projects"], dict):
                for pn, pc in data["projects"].items():
                    cfg["projects"].setdefault(pn, {"model_allowlist": [], "free_only": False})
                    if "model_allowlist" in pc: cfg["projects"][pn]["model_allowlist"] = pc["model_allowlist"]
                    if "free_only" in pc: cfg["projects"][pn]["free_only"] = pc["free_only"]
            save_config(cfg)
            self.send_json({"ok": True, "config": cfg})

        elif path == "/api/models":
            model_id = data.get("id")
            if not model_id: return self.send_error(400, json.dumps({"error": "Missing id"}))
            mdata = load_models_raw()
            found_idx = None
            for i, m in enumerate(mdata.get("models", [])):
                if m.get("id") == model_id: found_idx = i; break
            if found_idx is not None:
                existing = mdata["models"][found_idx]
                for key, val in data.items():
                    if key == "cost" and isinstance(val, dict) and isinstance(existing.get("cost"), dict):
                        existing["cost"].update(val)
                    elif key == "capabilities" and isinstance(val, dict) and isinstance(existing.get("capabilities"), dict):
                        existing["capabilities"].update(val)
                    else: existing[key] = val
                mdata["models"][found_idx] = existing
                save_models_raw(mdata)
                ms = model_summary(existing); ms["disabled"] = model_is_disabled(existing["id"], load_config())
                self.send_json({"ok": True, "action": "updated", "model": ms})
            else:
                mdata.setdefault("models", []).append(data)
                save_models_raw(mdata)
                ms = model_summary(data); ms["disabled"] = model_is_disabled(data.get("id", ""), load_config())
                self.send_json({"ok": True, "action": "created", "model": ms})
        else:
            self.send_error(404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/models" and "id" in qs:
            mid = qs["id"][0]
            data = load_models_raw()
            orig = len(data.get("models", []))
            data["models"] = [m for m in data.get("models", []) if m.get("id") != mid]
            if len(data["models"]) < orig:
                save_models_raw(data)
                self.send_json({"ok": True, "action": "deleted", "id": mid})
            else:
                self.send_error(404, json.dumps({"error": "Not found"}))

        elif path == "/api/project-doc":
            name = qs.get("name", [None])[0]
            fn = qs.get("file", [None])[0]
            if not name or not fn: return self.send_error(400, json.dumps({"error": "Missing name or file"}))
            if delete_project_doc(name, fn):
                self.send_json({"ok": True, "action": "deleted", "name": name, "file": fn})
            else:
                self.send_error(404, json.dumps({"error": "Not found or invalid"}))
        else:
            self.send_error(404)

    def serve_file(self, name, ct):
        p = os.path.join(os.path.dirname(__file__), name)
        if not os.path.exists(p): return self.send_error(404)
        with open(p) as f: c = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(c.encode())

    def send_json(self, d):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(json.dumps(d, indent=2, ensure_ascii=False).encode())
        except BrokenPipeError:
            pass

    def send_error(self, code, body=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if body: self.wfile.write(body.encode() if isinstance(body, str) else body)
        else: self.wfile.write(json.dumps({"error": f"HTTP {code}"}).encode())

    def log_message(self, fmt, *a):
        # Suppress noise from high-frequency polling endpoints
        path = a[1] if len(a) > 1 else ""
        if path in ("/api/live-agents", "/api/sse/live-sessions"):
            return
        print(f"[Dash] {a[0]} {path} {a[2]}")

    # ── SSE: Live Sessions ────────────────────────────────────────
    def _handle_sse_live(self):
        """Server-Sent Events endpoint that pushes live-sessions.json updates."""
        live_file = os.path.join(DATA_DIR, "live-sessions.json")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        last_mtime = 0
        try:
            while True:
                if os.path.exists(live_file):
                    mtime = os.path.getmtime(live_file)
                    if mtime > last_mtime:
                        last_mtime = mtime
                        with open(live_file) as f:
                            content = f.read()
                        self.wfile.write(f"data: {content}\n\n".encode())
                        self.wfile.flush()
                else:
                    self.wfile.write("data: {\"_meta\":{\"connected\":false,\"sessionCount\":0}}\n\n".encode())
                    self.wfile.flush()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # ── Gateway Tools Invoke ──────────────────────────────────────
    def _gateway_invoke(self, tool, args):
        """Call Gateway /tools/invoke and return result dict."""
        body = json.dumps({"tool": tool, "args": args}).encode()
        req = urllib.request.Request(
            f"http://{GATEWAY_HOST}:{GATEWAY_PORT}/tools/invoke",
            data=body,
            headers={
                "Authorization": f"Bearer {GATEWAY_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

if __name__ == "__main__":
    print(f"Dashboard v4 — http://localhost:{PORT}  Data: {DATA_DIR}")
    s = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try: s.serve_forever()
    except KeyboardInterrupt: print("\nStopped."); s.server_close()
