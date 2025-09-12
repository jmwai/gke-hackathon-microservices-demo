"""
FastAPI application for agents-gateway.

Conforms to ADK guidance: clear API surface, structured JSON, and minimal
agent/tool coupling at the HTTP layer. Endpoints are stubbed for Phase 1 and
will be wired to ADK Agents and FunctionTools incrementally.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException

from .schema import (
    QueryRequest,
    QueryResponseItem,
    ImageResponseItem,
    SupportRequest,
    SupportResponse,
    RecommendRequest,
    RecommendResponseItem,
)
from .config import get_settings, HealthSnapshot
from .db import health_check
from .agents import boutique_host_agent


settings = get_settings()
app = FastAPI(title="agents-gateway", version="0.1.0")


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


@app.post("/agent/query", response_model=list[QueryResponseItem])
def agent_query(req: QueryRequest) -> list[QueryResponseItem]:
    response = boutique_host_agent.run(
        query=req.text,
        filters=req.filters,
        top_k=min(req.top_k, settings.API_TOP_K_MAX)
    )
    if not response or not response.output:
        return []
    # The output of a router is the output of the sub-agent
    return [QueryResponseItem(**r) for r in response.output]


@app.post("/agent/image", response_model=list[ImageResponseItem])
async def agent_image(
    file: UploadFile = File(..., description="Image upload (jpg/png/webp)"),
    userContext: Optional[str] = Form(None),
    top_k: int = Form(10),
) -> list[ImageResponseItem]:
    # Validate content type
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Unsupported image type")
    data = await file.read()
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large")

    # TODO: parse userContext to extract filters
    response = boutique_host_agent.run(
        image_bytes=data,
        filters=None,
        top_k=min(top_k, settings.API_TOP_K_MAX)
    )
    if not response or not response.output:
        return []
    # The output of a router is the output of the sub-agent
    return [ImageResponseItem(**r) for r in response.output]


@app.post("/agent/support", response_model=SupportResponse)
def agent_support(req: SupportRequest) -> SupportResponse:
    # Extract context needed for support tools
    user_context = req.userContext or {}
    email = user_context.get("email", "guest@example.com")
    order_id = user_context.get("order_id", "ORDER-123")
    items = user_context.get("items", ["OLJ-001"])
    reason = user_context.get("reason", "doesn't fit")

    response = boutique_host_agent.run(
        message=req.text,
        email=email,
        order_id=order_id,
        items=items,
        reason=reason
    )
    output = response.output

    # The final output of the returns workflow is a dict (intent)
    if isinstance(output, dict):
        return SupportResponse(answer="", return_intent=output)

    # Otherwise, it's a string from the KB tool
    return SupportResponse(answer=str(output))


@app.post("/agent/recommend", response_model=list[RecommendResponseItem])
def agent_recommend(req: RecommendRequest) -> list[RecommendResponseItem]:
    # The user_key would typically come from an auth header
    user_key = req.userContext.get(
        "user_key", "guest") if req.userContext else "guest"
    response = boutique_host_agent.run(
        message="I'd like a recommendation.",
        user_key=user_key,
        top_k=min(req.top_k, settings.API_TOP_K_MAX)
    )
    if not response or not response.output:
        return []
    return [RecommendResponseItem(**r) for r in response.output]
