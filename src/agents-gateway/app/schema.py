from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    text: str = Field(..., min_length=1)
    userContext: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None
    top_k: int = Field(10, ge=1, le=50)


class ImageResponseItem(BaseModel):
    product: Dict[str, Any]
    distance: float
    why: Optional[str] = None


class QueryResponseItem(BaseModel):
    product: Dict[str, Any]
    distance: float
    why: Optional[str] = None


class SupportRequest(BaseModel):
    text: str
    userContext: Optional[Dict[str, Any]] = None


class SupportResponse(BaseModel):
    answer: str
    citations: Optional[list[str]] = None
    return_intent: Optional[Dict[str, Any]] = None


class RecommendRequest(BaseModel):
    userContext: Optional[Dict[str, Any]] = None


class RecommendResponseItem(BaseModel):
    product: Dict[str, Any]
    score: float
    why: Optional[str] = None
