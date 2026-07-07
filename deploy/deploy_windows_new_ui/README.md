# RedTeamer AI — Windows Deployment Guide

This directory contains PowerShell scripts to deploy **RedTeamer AI** on Windows for local autonomous agent red teaming, including:

- **api-server** — backend API (FastAPI, default port 8000)
- **attack-agent** — attack agent service (FastAPI, default port 9000)
- **observer-plugin** — event observer plugin installed into the local OpenClaw instance

Run scripts from this folder: `deploy/deploy_windows_new_ui/`.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Windows 10 / 11 | PowerShell 5.1 or later (built-in) |
| Python 3.11+ | Check "Add to PATH" during installation |
| OpenClaw | Installed and run at least once (to create `~\.openclaw\`) |
| Git | For fetching / updating source code |

> If Python is not installed, place a Python Embeddable Package (64-bit) `.zip` in the `python-embed\` directory — `install.ps1` will extract and use it automatically.

---

## Step 1 — Configure `.env`

Inside this directory (`deploy\deploy_windows_new_ui\`), copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Open `.env` in a text editor and fill in the values below.

### API Server

| Variable | Description | Example |
|----------|-------------|---------|
| `API_HOST` | Listen address | `0.0.0.0` |
| `API_PORT` | Listen port | `8000` |
| `DATABASE_URL` | SQLite database path | `sqlite:///./redteam.db` |
| `BYPASS_API_KEY` | API key for Web UI login (must match `AGENT_API_KEY`) | `my-secret-key` |
| `ADMIN_TOKEN` | Admin token for registering new clients | `my-admin-token` |

### Azure OpenAI

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint URL |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name (e.g. `gpt-4o-mini`) |
| `AZURE_OPENAI_API_VERSION` | API version (e.g. `2024-02-15-preview`) |

### Attack Agent

| Variable | Description | Example |
|----------|-------------|---------|
| `AGENT_HOST` | Listen address | `0.0.0.0` |
| `AGENT_PORT` | Listen port | `9000` |
| `AGENT_HOST_URL` | Externally reachable URL of the attack agent | `http://localhost:9000` |
| `CLOUD_API_URL` | URL of the api-server | `http://localhost:8000` |
| `AGENT_API_KEY` | Same value as `BYPASS_API_KEY` | `my-secret-key` |
| `CLIENT_NAME` | Name of this agent in the system | `default` |
| `OBSERVER_URL` | URL of the OpenClaw observer plugin (usually unchanged) | `http://127.0.0.1:18790` |
| `OPENCLAW_TIMEOUT` | Maximum seconds to wait per attack | `120` |
| `OPENCLAW_BIN` | **Windows only:** full path to `openclaw.cmd` | `C:\Users\<YourUsername>\AppData\Roaming\npm\openclaw.cmd` |

> **Notes:**
> - `BYPASS_API_KEY` and `AGENT_API_KEY` must have the same value, otherwise the attack agent cannot return results to the api-server.
> - `OPENCLAW_BIN` is only required on Windows. On macOS/Linux, `openclaw` is on `PATH` and this variable is not needed.

---

## Step 2 — Install

From this directory, run in PowerShell:

```powershell
.\install.ps1
```

The install script will automatically:

1. Detect the system Python (or use the embedded Python from `python-embed\`)
2. Create a shared virtual environment (`venv\`) and install all Python packages
3. Copy the observer plugin to `~\.openclaw\extensions\redteam-observer\`
4. Update `~\.openclaw\openclaw.json` to enable the redteam-observer plugin
5. Create `.env` from `.env.example` if `.env` does not yet exist

---

## Step 3 — Start Services

```powershell
.\start.ps1
```

Two windows will open:

- **api-server** → `http://localhost:8000` (Web UI entry point)
- **attack-agent** → `http://localhost:9000`

PIDs are recorded in `.pids.json` for use by `stop.ps1`.

---

## Step 4 — Stop Services

```powershell
.\stop.ps1
```

Terminates both services by PID and clears the PID record file.

---

## Step 5 — Log In to Web UI

1. Open `http://localhost:8000` in a browser
2. Enter the value of `BYPASS_API_KEY` from `.env` as the API key
3. Start a **test job** from the Attack page to run scenarios autonomously against your agent

---

## Updating the Deployment

When the source code has been updated:

```powershell
# 1. Stop services
.\stop.ps1

# 2. Pull latest code (run from repo root)
cd ..\..
git pull

# 3. Reinstall (only needed if dependencies changed)
cd deploy\deploy_windows_new_ui
.\install.ps1

# 4. Start services
.\start.ps1
```

---

## Troubleshooting

**Q: Install fails with `~\.openclaw not found`**
- OpenClaw has never been run. Run `openclaw` once first, then re-run `install.ps1`.

**Q: Start fails with `Not found: venv\...`**
- Not installed yet. Run `.\install.ps1` first.

**Q: `openclaw not found in PATH`**
- Make sure `OPENCLAW_BIN` is set to the correct path, replacing `<YourUsername>` with your actual Windows username:
  ```
  OPENCLAW_BIN=C:\Users\YourUsername\AppData\Roaming\npm\openclaw.cmd
  ```

**Q: Attack completes but no events are captured**
- Confirm OpenClaw is running and the observer plugin is loaded (OpenClaw startup log should include `redteam-observer`).
- Confirm `OBSERVER_URL` points to the correct port (default: `http://127.0.0.1:18790`).
