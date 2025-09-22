from __future__ import annotations

from google.adk.agents import Agent
from pydantic import BaseModel, Field
from typing import List, Optional

from .prompts import cart as cart_prompt
from .tools import add_to_cart_tool, get_cart_tool, place_order_tool
from .callbacks import before_tool_callback


GEMINI_MODEL = "gemini-2.5-flash"


class CartItem(BaseModel):
    product_id: str = Field(description="Product ID")
    name: str = Field(description="Product name")
    quantity: int = Field(description="Quantity")
    price: Optional[str] = Field(description="Unit price", default="")
    image: Optional[str] = Field(description="Product image URL", default="")
    line_total: Optional[str] = Field(
        description="Line total price", default="")


class CartDetails(BaseModel):
    cart_id: Optional[str] = Field(
        description="Cart identifier", default=None)  # Made optional
    items: List[CartItem] = Field(
        description="Items in cart", default_factory=list)  # Default to empty list
    total_price: Optional[str] = Field(description="Total price", default="")
    tax: Optional[str] = Field(description="Tax amount", default="")
    shipping: Optional[str] = Field(description="Shipping cost", default="")


class OrderDetails(BaseModel):
    order_id: Optional[str] = Field(
        description="Order confirmation ID", default=None)
    tracking_id: Optional[str] = Field(
        description="Shipping tracking ID", default=None)
    status: Optional[str] = Field(description="Order status", default=None)
    estimated_delivery: Optional[str] = Field(
        description="Estimated delivery date", default=None)
    message: Optional[str] = Field(
        description="Order confirmation message", default=None)


class ShoppingAssistantOutput(BaseModel):
    action: Optional[str] = Field(description="Action taken", default="")
    summary: Optional[str] = Field(description="Summary message", default="")
    cart: Optional[CartDetails] = Field(
        description="Cart details", default=None)
    order: Optional[OrderDetails] = Field(
        description="Order details for successful order placement", default=None)


cart_agent = Agent(
    name="cart_agent",
    description="Resolves ordinals 1..5 from last results and manages the cart (add/show/place orders).",
    instruction=cart_prompt.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[add_to_cart_tool, get_cart_tool, place_order_tool],
    output_schema=ShoppingAssistantOutput,
    output_key="shopping_recommendations",
    before_tool_callback=before_tool_callback,
)
