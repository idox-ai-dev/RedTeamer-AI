#!/bin/sh
# Sync bundled extensions and patch openclaw.json on first boot,
# then hand off to the real openclaw command.
set -e

OPENCLAW_HOME=/home/node/.openclaw
EXTENSIONS_DST=$OPENCLAW_HOME/extensions
EXTENSIONS_SRC=/opt/redteam-extensions
OPENCLAW_JSON=$OPENCLAW_HOME/openclaw.json

# ── 1. Sync bundled extensions into the config volume ─────────────
mkdir -p "$EXTENSIONS_DST"
for src in "$EXTENSIONS_SRC"/*/; do
  name=$(basename "$src")
  dst="$EXTENSIONS_DST/$name"
  echo "[entrypoint] Syncing extension: $name"
  rm -rf "$dst"
  cp -r "$src" "$dst"
done

# # ── 2. Sync mock-payment test-data into config volume ─────────────
TEST_DATA_SRC=/opt/mock-payment-mcp/test-data
TEST_DATA_DST=$OPENCLAW_HOME/test-data
if [ -d "$TEST_DATA_SRC" ]; then
  mkdir -p "$TEST_DATA_DST"
  cp -f "$TEST_DATA_SRC"/* "$TEST_DATA_DST"/
  echo "[entrypoint] Synced test-data: $(ls "$TEST_DATA_DST" | tr '\n' ' ')"
fi

# ── 3. Create minimal openclaw.json if missing (skip onboarding) ──
if [ ! -f "$OPENCLAW_JSON" ]; then
  echo "[entrypoint] openclaw.json not found — creating minimal config"
  mkdir -p "$OPENCLAW_HOME"
  GATEWAY_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-}"
  node -e "
    const cfg = {
      gateway: {
        mode: 'local',
        port: 18789,
        auth: { mode: 'token', token: '${GATEWAY_TOKEN}' },
        http: { endpoints: { chatCompletions: { enabled: true } } }
      },
      agents: { defaults: { workspace: '/home/node/.openclaw/workspace' } },
      session: { dmScope: 'per-channel-peer' },
    };
    require('fs').writeFileSync('$OPENCLAW_JSON', JSON.stringify(cfg, null, 2));
    console.log('[entrypoint] minimal openclaw.json created');
  "
fi

# ── 4. Patch openclaw.json with plugin + MCP registrations ────────
if [ -f "$OPENCLAW_JSON" ]; then
  node - <<'JS'
    const fs   = require('fs');
    const path = '/home/node/.openclaw/openclaw.json';
    const cfg  = JSON.parse(fs.readFileSync(path, 'utf8'));

    // always sync gateway auth token + allowed origins from env
    const gatewayToken = process.env.OPENCLAW_GATEWAY_TOKEN || '';
    // Use the numeric port from the config, not the K8s-injected OPENCLAW_GATEWAY_PORT
    // (K8s injects OPENCLAW_GATEWAY_PORT=tcp://<ip>:<port> which is not a bare port number)
    const gatewayPort  = (cfg.gateway && cfg.gateway.port) || 18789;
    cfg.gateway = cfg.gateway || {};
    if (gatewayToken) {
      cfg.gateway.auth = cfg.gateway.auth || {};
      cfg.gateway.auth.token = gatewayToken;
    }
    cfg.gateway.controlUi = cfg.gateway.controlUi || {};
    cfg.gateway.controlUi.allowedOrigins = [
      `http://localhost:${gatewayPort}`,
      `http://127.0.0.1:${gatewayPort}`,
    ];
    cfg.gateway.controlUi.dangerouslyAllowHostHeaderOriginFallback = true;

    // plugins
    cfg.plugins              = cfg.plugins              || {};
    cfg.plugins.allow        = cfg.plugins.allow        || [];
    cfg.plugins.entries      = cfg.plugins.entries      || {};

    if (!cfg.plugins.allow.includes('redteam-observer'))
      cfg.plugins.allow.push('redteam-observer');

    cfg.plugins.entries['redteam-observer'] = {
      enabled: true,
      hooks: { allowConversationAccess: true },
    };

    // MCP mock-payment server
    cfg.mcp         = cfg.mcp         || {};
    cfg.mcp.servers = cfg.mcp.servers || {};
    if (!cfg.mcp.servers['mock-payment']) {
      cfg.mcp.servers['mock-payment'] = {
        command: '/opt/mcp-venv/bin/python',
        args:    ['/opt/mock-payment-mcp/server.py'],
      };
    }

    // LiteLLM model provider
    const litellmUrl   = process.env.LITELLM_BASE_URL  || 'http://host.docker.internal:4000/v1';
    const litellmKey   = process.env.LITELLM_API_KEY   || 'sk-1234';
    const litellmModel = process.env.LITELLM_MODEL_ID  || 'gpt-5-mini';
    const litellmName  = process.env.LITELLM_MODEL_NAME|| 'GPT-5 Mini (Azure)';

    cfg.models         = cfg.models         || {};
    cfg.models.mode    = 'merge';
    cfg.models.providers = cfg.models.providers || {};
    cfg.models.providers.litellm = {
      baseUrl: litellmUrl,
      apiKey:  litellmKey,
      api:     'openai-completions',
      models: [{
        id:            litellmModel,
        name:          litellmName,
        reasoning:     false,
        input:         ['text', 'image'],
        contextWindow: 128000,
        maxTokens:     16384,
      }],
    };

    cfg.agents = cfg.agents || {};
    cfg.agents.defaults = cfg.agents.defaults || {};
    cfg.agents.defaults.model = cfg.agents.defaults.model || {};
    cfg.agents.defaults.model.primary = cfg.agents.defaults.model.primary || `litellm/${litellmModel}`;

    fs.writeFileSync(path, JSON.stringify(cfg, null, 2));
    console.log(`[entrypoint] openclaw.json patched: redteam-observer + mock-payment + litellm (${litellmUrl})`);
JS
else
  echo "[entrypoint] WARNING: openclaw.json not found after creation attempt"
fi

exec "$@"
