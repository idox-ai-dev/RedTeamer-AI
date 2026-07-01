from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


OPENCLAW_TIMEOUT = int(os.environ.get("OPENCLAW_TIMEOUT", "300"))
OPENCLAW_BIN     = os.environ.get("OPENCLAW_BIN", "openclaw")


def run(session_key: str, message: str, timeout: int = OPENCLAW_TIMEOUT) -> CliResult:
    log.info("[cli_adapter] Running openclaw: session=%s message_len=%d timeout=%ds",
             session_key, len(message), timeout)
    try:
        if sys.platform == "win32":
            # openclaw.cmd goes through cmd.exe which treats newlines as command
            # terminators even inside quoted arguments — flatten to spaces first.
            msg_flat = message.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
            msg_flat = msg_flat.replace('"', "'")
            esc_bin  = OPENCLAW_BIN.replace("'", "''")
            esc_key  = session_key.replace("'", "''")
            esc_msg  = msg_flat.replace("'", "''")
            ps_cmd   = f"& '{esc_bin}' agent --session-id '{esc_key}' --message '{esc_msg}' --json"
            args = ["powershell", "-ExecutionPolicy", "Bypass", "-NonInteractive", "-Command", ps_cmd]
        else:
            args = [OPENCLAW_BIN, "agent", "--local", "--session-id", session_key, "--message", message, "--json"]
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
        )
        log.info("[cli_adapter] openclaw finished: session=%s exit=%d", session_key, proc.returncode)
        return CliResult(returncode=proc.returncode, stdout=proc.stdout or "", stderr=proc.stderr or "")
    except subprocess.TimeoutExpired:
        log.warning("[cli_adapter] openclaw timed out after %ds: session=%s", timeout, session_key)
        return CliResult(returncode=-1, stdout="", stderr="", timed_out=True)
    except FileNotFoundError:
        log.error("[cli_adapter] openclaw binary not found: %s", OPENCLAW_BIN)
        return CliResult(returncode=-1, stdout="", stderr="openclaw binary not found", timed_out=False)
    except Exception as exc:
        log.error("[cli_adapter] subprocess error: %s", exc)
        return CliResult(returncode=-1, stdout="", stderr=str(exc), timed_out=False)
