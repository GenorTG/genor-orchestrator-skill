#!/bin/bash
# Orchestration Dashboard v4 - PM2 launcher
export DASHBOARD_PORT="${DASHBOARD_PORT:-8767}"
export ORCHESTRATOR_DATA_DIR="${ORCHESTRATOR_DATA_DIR:-$HOME/.openclaw/workspace/orchestrator-data}"
cd "$(dirname "$0")"
exec python3 server.py
