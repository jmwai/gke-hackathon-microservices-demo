from __future__ import annotations
from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field
from typing import List, Optional
from .prompts import recommendation
from .tools import user_context_tool, text_search_tool


GEMINI_MODEL = "gemini-2.5-flash"


class RecommendationResult(BaseModel):
    id: str = Field(description="Product ID")
    name: str = Field(description="Product name")  
    description: str = Field(description="Product description")
    picture: str = Field(description="Product image URL")
    why: str = Field(description="Why this product is recommended for the user's request")
    price_range: Optional[str] = Field(description="Price range or specific price", default="")
    distance: Optional[float] = Field(description="Search relevance score", default=0.0)


class UserContext(BaseModel):
    user_key: Optional[str] = Field(description="User identifier", default=None)
    preferences: Optional[dict] = Field(description="User preferences and filters", default=None)
    request: str = Field(description="Original user request for recommendations")


class ShoppingAssistantOutput(BaseModel):
    recommendations: List[RecommendationResult] = Field(description="Product recommendations")
    user_context: UserContext = Field(description="User context and preferences")
    recommendation_summary: str = Field(description="Overall summary of why these recommendations fit the request")
    total_recommendations: int = Field(description="Number of recommendations provided")


# Recommendation Agent (ADK LlmAgent)
# Provides personalized product recommendations.
root_agent = LlmAgent(
    name="shopping_assistant_agent",
    description="Provides personalized product recommendations by first fetching user context and then searching for relevant products.",
    instruction=recommendation.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[user_context_tool, text_search_tool],
    output_schema=ShoppingAssistantOutput,
    output_key="shopping_recommendations"
)
