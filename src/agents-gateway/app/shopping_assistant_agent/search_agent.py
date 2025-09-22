from __future__ import annotations

from google.adk.agents import Agent
from pydantic import BaseModel, Field
from typing import List, Optional

from .prompts import search as search_prompt
from .tools import text_search_tool, image_search_tool
from .callbacks import after_tool_callback, before_model_callback, before_tool_callback

GEMINI_MODEL = "gemini-2.5-flash"


class RecommendationResult(BaseModel):
    id: str = Field(description="Product ID")
    name: str = Field(description="Product name")
    description: str = Field(description="Product description")
    picture: str = Field(description="Product image URL")
    price_range: Optional[str] = Field(
        description="Price range or specific price", default="")
    distance: Optional[float] = Field(
        description="Search relevance score", default=0.0)
    price: Optional[float] = Field(description="Unit price", default=0.0)


class ShoppingAssistantOutput(BaseModel):
    action: Optional[str] = Field(description="Action taken", default="")
    summary: Optional[str] = Field(description="Summary message", default="")
    recommendations: Optional[List[RecommendationResult]] = Field(
        description="Product recommendations (max 5)", default_factory=list, max_length=5
    )
    recommendation_summary: Optional[str] = Field(
        description="A summary of the search results.", default=""
    )


search_agent = Agent(
    name="search_agent",
    description="Finds and presents up to 5 numbered products with a brief summary.",
    instruction=search_prompt.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[text_search_tool, image_search_tool],
    output_schema=ShoppingAssistantOutput,
    output_key="shopping_recommendations",
    before_model_callback=before_model_callback,
    before_tool_callback=before_tool_callback,
    after_tool_callback=after_tool_callback,
)
