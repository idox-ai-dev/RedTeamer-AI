# Deployment

| Path | Description |
|------|-------------|
| [`docker/`](docker/) | Docker Compose stack (OpenClaw gateway, attack agent, API server + Web UI) |
| [`deploy_windows_new_ui/`](deploy_windows_new_ui/) | Windows PowerShell install/start/stop scripts for local deployment |

**Docker Compose (from repo root):**

```bash
cd deploy/docker
cp .env.example .env
docker compose up --build
```

**Windows:** see [deploy_windows_new_ui/README.md](deploy_windows_new_ui/README.md).
