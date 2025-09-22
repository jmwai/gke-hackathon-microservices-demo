from __future__ import annotations
from google.adk.agents import LlmAgent, SequentialAgent
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from .prompts import confirm_cart, submit_order
from .tools import get_cart_details_tool, place_order_tool

GEMINI_MODEL = "gemini-2.5-flash"


class CartItem(BaseModel):
    product_id: str = Field(description="Product ID")
    name: str = Field(description="Product name")
    quantity: int = Field(description="Quantity")
    price: Optional[str] = Field(description="Item price", default="")


class CartDetails(BaseModel):
    cart_id: str = Field(description="Cart identifier")
    items: List[CartItem] = Field(description="Items in cart")
    total_price: str = Field(description="Total cart price")
    tax: Optional[str] = Field(description="Tax amount", default="")
    shipping: Optional[str] = Field(description="Shipping cost", default="")


class OrderConfirmation(BaseModel):
    order_id: str = Field(description="Generated order ID")
    status: str = Field(description="Order status (success, failed, pending)")
    shipping_tracking_id: Optional[str] = Field(
        description="Shipping tracking ID", default="")
    estimated_delivery: Optional[str] = Field(
        description="Estimated delivery date", default="")
    message: str = Field(description="Confirmation message")


class CheckoutStepResult(BaseModel):
    step: str = Field(
        description="Current checkout step (cart_confirmation, order_submission)")
    action: str = Field(
        description="Action taken (display_cart, confirm_order, place_order)")
    cart_details: Optional[CartDetails] = Field(
        description="Cart information", default=None)
    order_confirmation: Optional[OrderConfirmation] = Field(
        description="Order confirmation details", default=None)
    requires_user_input: bool = Field(
        description="Whether user input is required to proceed")
    next_step: Optional[str] = Field(
        description="Next step in checkout process", default=None)


class CheckoutOutput(BaseModel):
    checkout_result: CheckoutStepResult = Field(
        description="Checkout step result")
    success: bool = Field(
        description="Whether the checkout step was successful")
    ready_to_proceed: bool = Field(
        description="Whether ready to proceed to next step")


confirm_cart_agent = LlmAgent(
    instruction=confirm_cart.INSTRUCTION,
    name="confirm_cart_agent",
    description="Confirms the final cart details with the user before payment.",
    model=GEMINI_MODEL,
    tools=[get_cart_details_tool],
    output_schema=CheckoutOutput,
    output_key="cart_confirmation_result",
)

submit_order_agent = LlmAgent(
    instruction=submit_order.INSTRUCTION,
    name="submit_order_agent",
    description="Collects final details and places the order.",
    model=GEMINI_MODEL,
    tools=[place_order_tool],
    output_schema=CheckoutOutput,
    output_key="order_submission_result",
)

root_agent = SequentialAgent(
    name="checkout_agent",
    description="Guides the user through the checkout process.",
    sub_agents=[
        confirm_cart_agent,
        submit_order_agent,
    ],
)
