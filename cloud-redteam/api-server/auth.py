from __future__ import annotations

import os
from typing import Optional

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models_db import Client


ADMIN_TOKEN    = os.environ.get("ADMIN_TOKEN", "")
# BYPASS_API_KEY: local PoC / demo convenience only.
# Leave unset (empty string) in production — the bypass path is disabled when this is empty.
BYPASS_API_KEY = os.environ.get("BYPASS_API_KEY", "")

_BYPASS_CLIENT = Client(
    id="bypass-000000000000",
    name="bypass",
    api_key=BYPASS_API_KEY,
    agent_url=os.environ.get("DEFAULT_AGENT_URL", "") or None,
    registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
)


def get_current_client(
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Client:
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing X-API-Key header")
    if BYPASS_API_KEY and x_api_key == BYPASS_API_KEY:
        return _BYPASS_CLIENT
    client = db.query(Client).filter(Client.api_key == x_api_key).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid API key")
    from datetime import datetime, timezone
    client.last_seen = datetime.now(timezone.utc)
    db.commit()
    return client


def verify_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Invalid admin token")
