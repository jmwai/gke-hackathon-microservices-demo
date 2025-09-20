from __future__ import annotations
from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field
from typing import List, Optional
from .prompts import recommendation
from .tools import text_search_tool, image_search_tool, add_to_cart_tool, get_cart_tool, place_order_tool


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


class CartItem(BaseModel):
    product_id: str = Field(description="Product ID")
    name: str = Field(description="Product name")
    quantity: int = Field(description="Quantity")
    price: Optional[str] = Field(description="Line price", default="")


class CartDetails(BaseModel):
    cart_id: str = Field(description="Cart identifier")
    items: List[CartItem] = Field(description="Items in cart")
    total_price: Optional[str] = Field(description="Total price", default="")
    tax: Optional[str] = Field(description="Tax amount", default="")
    shipping: Optional[str] = Field(description="Shipping cost", default="")


class OrderResult(BaseModel):
    order_id: str = Field(description="Order identifier")
    status: str = Field(description="Order status")
    tracking_id: Optional[str] = Field(description="Tracking ID", default="")
    estimated_delivery: Optional[str] = Field(description="ETA", default="")
    message: Optional[str] = Field(
        description="Confirmation message", default="")


class ShoppingAssistantOutput(BaseModel):
    action: Optional[str] = Field(description="Action taken", default="")
    summary: Optional[str] = Field(description="Summary message", default="")

    recommendations: Optional[List[RecommendationResult]] = Field(
        description="Product recommendations", default_factory=list
    )
    recommendation_summary: Optional[str] = Field(
        description="A summary of the search results.", default=""
    )

    cart: Optional[CartDetails] = Field(
        description="Cart details", default=None)
    order: Optional[OrderResult] = Field(
        description="Order result", default=None)


# Recommendation Agent (ADK LlmAgent)
# Provides personalized product recommendations.
root_agent = LlmAgent(
    name="shopping_assistant_agent",
    description="Provides personalized product recommendations by searching for relevant products.",
    instruction=recommendation.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[text_search_tool, image_search_tool, add_to_cart_tool,
           get_cart_tool, place_order_tool],
    output_schema=ShoppingAssistantOutput,
    output_key="shopping_recommendations"
)
