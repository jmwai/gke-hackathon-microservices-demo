"""
FastAPI application for agents-gateway.

Conforms to ADK guidance: clear API surface, structured JSON, and minimal
agent/tool coupling at the HTTP layer. Endpoints are stubbed for Phase 1 and
will be wired to ADK Agents and FunctionTools incrementally.
"""
from __future__ import annotations

# CRITICAL: Import warning suppression FIRST before any other imports!
import app.suppress_warnings  # This MUST be the first import!

# Standard library imports
import os
import uuid

# Third-party imports (safe after warning suppression)
from typing import Any, Dict
from fastapi import FastAPI
import vertexai
from vertexai import agent_engines
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.memory import VertexAiMemoryBankService
from google.adk.sessions import VertexAiSessionService

# Local imports
from .common.config import get_settings, HealthSnapshot
from .common.db import health_check
from .common.utils import fetch_google_api_key, get_or_create_agent_engine


# Fetch API Key from Secret Manager
try:
    fetch_google_api_key()
    print("API key fetch completed")
except Exception as e:
    print(f"ERROR: Failed to fetch API key: {e}")

try:
    settings = get_settings()
    print("Settings loaded successfully")
except Exception as e:
    print(f"ERROR: Failed to load settings: {e}")
    raise

# Vertex AI initialization
try:
    os.environ["GOOGLE_CLOUD_PROJECT"] = settings.PROJECT_ID
    os.environ["GOOGLE_CLOUD_LOCATION"] = settings.REGION

    vertexai.init(project=settings.PROJECT_ID, location=settings.REGION)
    print("Vertex AI initialized successfully")
except Exception as e:
    print(f"ERROR: Failed to initialize Vertex AI: {e}")
    raise

# Agent Engine creation
# Use a stable display name to ensure we reuse the same engine
AGENT_ENGINE_DISPLAY_NAME = "online-boutique-agent-engine"
try:
    agent_engine = get_or_create_agent_engine(AGENT_ENGINE_DISPLAY_NAME)
    print(f"Agent engine ready: {agent_engine.resource_name}")
except Exception as e:
    print(f"ERROR: Failed to create/get agent engine: {e}")
    raise

agent_engine_id = agent_engine.resource_name

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWED_ORIGINS = ["http://localhost", "http://localhost:8080", "*"]
SERVE_WEB_INTERFACE = False
# Construct the URI strings for the managed services using the correct scheme
SESSION_SERVICE_URI = f"agentengine://{agent_engine_id}"
MEMORY_BANK_SERVICE_URI = f"agentengine://{agent_engine_id}"

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    # session_service_uri=SESSION_SERVICE_URI,
    memory_service_uri=MEMORY_BANK_SERVICE_URI,
    allow_origins=ALLOWED_ORIGINS,
    web=SERVE_WEB_INTERFACE,
    trace_to_cloud=True,
)

print("ADK FastAPI app created successfully")


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    # snap = HealthSnapshot(
    #     project=settings.PROJECT_ID,
    #     region=settings.REGION,
    #     top_k_max=settings.API_TOP_K_MAX,
    #     upload_mb_max=settings.MAX_UPLOAD_MB,
    # )
    # db = health_check()
    # return {"status": "ok", "config": snap.model_dump(), "db": db}
    return {"status": "ok", "message": "Agents Gateway is healthy"}
