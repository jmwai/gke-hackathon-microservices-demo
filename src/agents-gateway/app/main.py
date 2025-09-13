"""
FastAPI application for agents-gateway.

Conforms to ADK guidance: clear API surface, structured JSON, and minimal
agent/tool coupling at the HTTP layer. Endpoints are stubbed for Phase 1 and
will be wired to ADK Agents and FunctionTools incrementally.
"""
from __future__ import annotations
import os

from typing import Any, Dict
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app

from .config import get_settings, HealthSnapshot
from .db import health_check

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_SERVICE_URI = "sqlite:///./sessions.db"
ALLOWED_ORIGINS = ["http://localhost", "http://localhost:8080", "*"]
SERVE_WEB_INTERFACE = False

settings = get_settings()

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    session_service_uri=SESSION_SERVICE_URI,
    allow_origins=ALLOWED_ORIGINS,
    web=SERVE_WEB_INTERFACE,
)


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    snap = HealthSnapshot(
        project=settings.PROJECT_ID,
        region=settings.REGION,
        top_k_max=settings.API_TOP_K_MAX,
        upload_mb_max=settings.MAX_UPLOAD_MB,
    )
    db = health_check()
    return {"status": "ok", "config": snap.model_dump(), "db": db}
