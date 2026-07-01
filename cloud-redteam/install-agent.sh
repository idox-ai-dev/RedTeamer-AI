#!/usr/bin/env bash
# install-agent.sh — Install attack-agent + redteam-observer on the attacker host
# Usage:
#   ./install-agent.sh \
#     --cloud-url    http://<api-server-host>:8000 \
#     --bypass-key   <BYPASS_API_KEY from api-server .env> \
#     --agent-url    http://<this-host>:9000
#
#   --bypass-key skips client registration entirely (POC mode).
#   If omitted, provide --admin-token and --client-name to register normally.
#
# Prerequisites: python3 (>=3.10), openclaw CLI, node/npm

set -euo pipefail

# ── Defaults ───────────────────────────────────────────────────────
CLOUD_API_URL=""
BYPASS_KEY=""
ADMIN_TOKEN=""
CLIENT_NAME=""
AGENT_HOST_URL=""
AGENT_PORT=9000

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATTACK_AGENT_DIR="$SCRIPT_DIR/attack-agent"
OBSERVER_SRC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/observer-plugin"
OBSERVER_DST_DIR="$HOME/.openclaw/extensions/redteam-observer"
OPENCLAW_JSON="$HOME/.openclaw/openclaw.json"
VENV_DIR="$ATTACK_AGENT_DIR/.venv"

# ── Colours ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${BLUE}[info]${NC}  $*"; }
ok()      { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
err()     { echo -e "${RED}[error]${NC} $*" >&2; }
section() { echo -e "\n${BOLD}── $* ──${NC}"; }

# ── Arg parsing ────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cloud-url)   CLOUD_API_URL="$2";   shift 2 ;;
    --bypass-key)  BYPASS_KEY="$2";      shift 2 ;;
    --admin-token) ADMIN_TOKEN="$2";     shift 2 ;;
    --client-name) CLIENT_NAME="$2";     shift 2 ;;
    --agent-url)   AGENT_HOST_URL="$2";  shift 2 ;;
    --port)        AGENT_PORT="$2";      shift 2 ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# //'
      exit 0 ;;
    *) err "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Interactive prompts ───────────────────────────────────────────
prompt() {
  local var="$1" label="$2" default="$3"
  if [[ -z "${!var}" ]]; then
    if [[ -n "$default" ]]; then
      read -rp "  $label [$default]: " val
      eval "$var=\"${val:-$default}\""
    else
      read -rp "  $label: " val
      eval "$var=\"$val\""
    fi
  fi
}

echo -e "\n${BOLD}OpenClaw Red Team — Attack Host Installer${NC}"
echo    "─────────────────────────────────────────"
prompt CLOUD_API_URL  "Cloud API URL (api-server)"                 "http://localhost:8000"
prompt AGENT_HOST_URL "This host's URL (reachable from cloud)"     "http://$(hostname -s):$AGENT_PORT"

# Determine auth mode
if [[ -z "$BYPASS_KEY" && -z "$ADMIN_TOKEN" ]]; then
  echo -e "  ${YELLOW}Auth mode:${NC} enter bypass key (blank = use admin-token registration)"
  read -rsp "  Bypass key (BYPASS_API_KEY): " BYPASS_KEY
  echo ""
fi

if [[ -z "$BYPASS_KEY" ]]; then
  prompt ADMIN_TOKEN  "Admin token (ADMIN_TOKEN)"    ""
  prompt CLIENT_NAME  "Client name for this host"    "$(hostname -s)"
fi

# ── Prerequisite checks ───────────────────────────────────────────
section "Checking prerequisites"

check_cmd() {
  if command -v "$1" &>/dev/null; then
    ok "$1 found ($(command -v "$1"))"
  else
    err "$1 not found — please install it first"
    exit 1
  fi
}

check_cmd python3
check_cmd openclaw
check_cmd node
check_cmd npm

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python version: $PY_VERSION"
if python3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)"; then
  ok "Python >= 3.10"
else
  err "Python 3.10+ required (found $PY_VERSION)"
  exit 1
fi

# ── 1. attack-agent — Python venv ────────────────────────────────
section "1/3  Installing attack-agent"

info "Creating virtualenv at $VENV_DIR"
python3 -m venv "$VENV_DIR"
ok "Virtualenv created"

info "Installing Python dependencies"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$ATTACK_AGENT_DIR/requirements.txt"
ok "Dependencies installed"

# ── 2. attack-agent — .env ────────────────────────────────────────
section "2/3  Configuring attack-agent .env"

ENV_FILE="$ATTACK_AGENT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  cp "$ENV_FILE" "$ENV_FILE.bak"
  warn ".env already exists — backed up to .env.bak"
fi

# ── Determine API key (bypass or register) ────────────────────────
if [[ -n "$BYPASS_KEY" ]]; then
  AGENT_API_KEY_VALUE="$BYPASS_KEY"
  CLIENT_NAME="${CLIENT_NAME:-bypass}"
  ok "Bypass mode — skipping client registration"
else
  info "Registering client '$CLIENT_NAME' with cloud at $CLOUD_API_URL"
  REGISTER_RESPONSE=$(python3 - <<PYEOF
import urllib.request, urllib.error, json

url  = "$CLOUD_API_URL/api/v1/clients/register"
body = json.dumps({"name": "$CLIENT_NAME", "agent_url": "$AGENT_HOST_URL"}).encode()
req  = urllib.request.Request(url, data=body, headers={
    "Content-Type": "application/json",
    "X-Admin-Token": "$ADMIN_TOKEN",
})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
        print(json.dumps({"ok": True, "api_key": data.get("api_key", "")}))
except urllib.error.HTTPError as e:
    code = e.code
    print(json.dumps({"ok": False, "error": f"HTTP {code}", "already": code == 409}))
except Exception as ex:
    print(json.dumps({"ok": False, "error": str(ex), "already": False}))
PYEOF
)
  AGENT_API_KEY_VALUE=$(python3 -c "import json; d=json.loads('''$REGISTER_RESPONSE'''); print(d.get('api_key',''))" 2>/dev/null || echo "")
  ALREADY=$(python3 -c "import json; d=json.loads('''$REGISTER_RESPONSE'''); print(d.get('already', False))" 2>/dev/null || echo "False")

  if [[ -n "$AGENT_API_KEY_VALUE" ]]; then
    ok "Client registered — API key obtained"
  elif [[ "$ALREADY" == "True" ]]; then
    warn "Client '$CLIENT_NAME' already registered. Paste the existing API key:"
    read -rsp "  AGENT_API_KEY: " AGENT_API_KEY_VALUE
    echo ""
  else
    warn "Cloud unreachable — you can set AGENT_API_KEY in .env manually later"
    AGENT_API_KEY_VALUE=""
  fi
fi

cat > "$ENV_FILE" <<EOF
# Cloud API connection
CLOUD_API_URL=$CLOUD_API_URL
AGENT_API_KEY=$AGENT_API_KEY_VALUE

# Agent identity
CLIENT_NAME=$CLIENT_NAME
ADMIN_TOKEN=${ADMIN_TOKEN:-}

# Agent server
AGENT_HOST=0.0.0.0
AGENT_PORT=$AGENT_PORT
AGENT_HOST_URL=$AGENT_HOST_URL

# Observer plugin
OBSERVER_URL=http://127.0.0.1:18790

# OpenClaw CLI
OPENCLAW_TIMEOUT=120
EOF

ok ".env written to $ENV_FILE"

# ── 3. observer-plugin — install to ~/.openclaw/extensions ────────
section "3/3  Installing redteam-observer plugin"

if [[ ! -d "$OBSERVER_SRC_DIR" ]]; then
  err "observer-plugin source not found at $OBSERVER_SRC_DIR"
  exit 1
fi

info "Copying plugin to $OBSERVER_DST_DIR"
mkdir -p "$HOME/.openclaw/extensions"
rm -rf "$OBSERVER_DST_DIR"
cp -r "$OBSERVER_SRC_DIR" "$OBSERVER_DST_DIR"

info "Installing npm dependencies"
(cd "$OBSERVER_DST_DIR" && npm install --silent)
ok "observer-plugin installed"

# ── Register plugin in openclaw.json ─────────────────────────────
info "Registering plugin in $OPENCLAW_JSON"

if [[ ! -f "$OPENCLAW_JSON" ]]; then
  warn "openclaw.json not found — creating minimal config"
  mkdir -p "$(dirname "$OPENCLAW_JSON")"
  echo '{}' > "$OPENCLAW_JSON"
fi

python3 - <<PYEOF
import json, sys
path = "$OPENCLAW_JSON"
with open(path) as f:
    cfg = json.load(f)

# plugins.allow
cfg.setdefault("plugins", {}).setdefault("allow", [])
if "redteam-observer" not in cfg["plugins"]["allow"]:
    cfg["plugins"]["allow"].append("redteam-observer")

# plugins.entries
cfg["plugins"].setdefault("entries", {})
cfg["plugins"]["entries"]["redteam-observer"] = {
    "enabled": True,
    "hooks": {"allowConversationAccess": True},
}

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)

print("  openclaw.json updated")
PYEOF

ok "Plugin registered"

# ── Done ─────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}Installation complete!${NC}"
echo "─────────────────────"
echo -e "${BOLD}Start the attack-agent:${NC}"
echo ""
echo "  cd $ATTACK_AGENT_DIR"
echo "  .venv/bin/python main.py"
echo ""
echo -e "${BOLD}Or as a background service:${NC}"
echo ""
echo "  nohup $ATTACK_AGENT_DIR/.venv/bin/python $ATTACK_AGENT_DIR/main.py \\"
echo "    > /tmp/attack-agent.log 2>&1 &"
echo ""
echo -e "${YELLOW}Note:${NC} Restart openclaw after installing the observer plugin"
echo "      so it loads the redteam-observer extension."
echo ""
echo -e "${YELLOW}Note:${NC} On first start, the agent will auto-register with the cloud"
echo "      using CLIENT_NAME='$CLIENT_NAME' and the ADMIN_TOKEN."
echo "      The issued API_KEY will be printed to the log."
