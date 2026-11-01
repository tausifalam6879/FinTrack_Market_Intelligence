#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Gateway code is unchanged; only rebuild the research API.
bash "$REPO_ROOT/scripts/deploy_agent_speed_fix.sh"
python3 "$REPO_ROOT/scripts/check_peer_recovery.py"
