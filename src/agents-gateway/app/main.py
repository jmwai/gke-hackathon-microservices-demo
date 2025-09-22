"""
FastAPI application for agents-gateway.

Conforms to ADK guidance: clear API surface, structured JSON, and minimal
agent/tool coupling at the HTTP layer. Endpoints are stubbed for Phase 1 and
will be wired to ADK Agents and FunctionTools incrementally.
"""
from __future__ import annotations

# CRITICAL: Import warning suppression FIRST before any other imports!
import app.suppress_warnings  # This MUST be the first import!
import logging
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

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)

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
print(f"Agent engine ID: {agent_engine_id}")
# Per the ADK source code (fast_api.py), the get_fast_api_app helper
# expects URI strings for service configuration.
# The `agent_engine_id` variable already contains the full resource name.
SESSION_SERVICE_URI = f"agentengine://{agent_engine_id}"
MEMORY_BANK_SERVICE_URI = f"agentengine://{agent_engine_id}"
app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    session_service_uri=SESSION_SERVICE_URI,
    memory_service_uri=MEMORY_BANK_SERVICE_URI,
    allow_origins=ALLOWED_ORIGINS,
    web=SERVE_WEB_INTERFACE,
    trace_to_cloud=False,
)

print("ADK FastAPI app created successfully")


@app.middleware("http")
async def log_requests(request, call_next):
    import time
    start_time = time.time()
    print(f"Request: {request.method} {request.url}")
    response = await call_next(request)
    process_time = time.time() - start_time
    print(f"Response: {response.status_code} in {process_time:.2f}s")
    return response


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"status": "ok", "message": "Agents Gateway is healthy"}
