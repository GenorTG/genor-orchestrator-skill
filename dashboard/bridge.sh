#!/bin/bash
# bridge.sh — Gateway WS Bridge for live session data + chat outbox
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
node gateway-ws-bridge.js
