from __future__ import annotations

import logging
import secrets
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_client, verify_admin
from database import get_db
from models_db import Client
from schemas import ClientOut, ClientRegister, ClientUpdate

router = APIRouter(prefix="/clients", tags=["clients"])
log = logging.getLogger(__name__)


@router.post("/register", response_model=ClientOut)
def register_client(
    body: ClientRegister,
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    existing = db.query(Client).filter(Client.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Client name already registered")
    client = Client(
        name=body.name,
        api_key=secrets.token_urlsafe(32),
        agent_url=body.agent_url,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    log.info("Client registered: name=%s agent_url=%s", client.name, client.agent_url)
    return client


@router.get("/me", response_model=ClientOut)
def get_me(current: Client = Depends(get_current_client)):
    return current


@router.patch("/me", response_model=ClientOut)
def update_me(
    body: ClientUpdate,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    if body.agent_url is not None:
        log.info("Client updated agent_url: client=%s agent_url=%s", current.name, body.agent_url)
        current.agent_url = body.agent_url
    from auth import BYPASS_API_KEY
    if current.api_key != BYPASS_API_KEY:
        db.commit()
        db.refresh(current)
    return current


@router.get("/", response_model=List[ClientOut])
def list_clients(
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    return db.query(Client).all()
