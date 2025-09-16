from __future__ import annotations
from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field
from typing import List, Optional
from .prompts import product_discovery
from .tools import text_search_tool, image_search_tool

GEMINI_MODEL = "gemini-2.5-flash"


class ProductResult(BaseModel):
    id: str = Field(description="Product ID")
    name: str = Field(description="Product name")
    description: Optional[str] = Field(
        description="Product description", default="")
    picture: Optional[str] = Field(description="Product image URL", default="")
    distance: Optional[float] = Field(
        description="Search relevance score", default=0.0)


class ProductSearchOutput(BaseModel):
    products: List[ProductResult] = Field(description="List of found products")
    summary: Optional[str] = Field(
        description="Brief summary of search results", default="")


# Product Discovery Agent (ADK LlmAgent)
# Responds to natural language queries about products.
root_agent = LlmAgent(
    name="product_discovery_agent",
    description="Responds to natural language queries about products by using text-based search or image-based vector search.",
    instruction=product_discovery.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[text_search_tool],
    output_schema=ProductSearchOutput,
    output_key="search_results"
)
