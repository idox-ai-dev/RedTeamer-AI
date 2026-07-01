#!/usr/bin/env python3
"""
Helper script to register mock-payment MCP server into Claude Code settings.
Run once before testing. Removes itself cleanly with --uninstall.
"""

import json
import sys
from pathlib import Path

SERVER_NAME = "mock-payment"
SERVER_PATH = Path(__file__).parent / "server.py"

SETTINGS_CANDIDATES = [
    Path.home() / ".claude" / "settings.json",
    Path(".claude") / "settings.json",
]


def find_settings() -> Path:
    for p in SETTINGS_CANDIDATES:
        if p.exists():
            return p
    # Create user-level settings if none exist
    p = SETTINGS_CANDIDATES[0]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    return p


def install():
    path = find_settings()
    data = json.loads(path.read_text())
    data.setdefault("mcpServers", {})
    data["mcpServers"][SERVER_NAME] = {
        "command": "python3",
        "args": [str(SERVER_PATH)],
    }
    path.write_text(json.dumps(data, indent=2))
    print(f"[install] Registered '{SERVER_NAME}' in {path}")
    print(f"[install] Restart Claude Code / openclaw to load the MCP server.")


def uninstall():
    path = find_settings()
    data = json.loads(path.read_text())
    removed = data.get("mcpServers", {}).pop(SERVER_NAME, None)
    path.write_text(json.dumps(data, indent=2))
    if removed:
        print(f"[uninstall] Removed '{SERVER_NAME}' from {path}")
    else:
        print(f"[uninstall] '{SERVER_NAME}' was not registered.")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()
