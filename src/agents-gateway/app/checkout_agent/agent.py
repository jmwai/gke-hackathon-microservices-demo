from __future__ import annotations
from google.adk.agents import LlmAgent, SequentialAgent
from .prompts import confirm_cart, submit_order
from .tools import get_cart_details_tool, place_order_tool

GEMINI_MODEL = "gemini-2.5-flash"

confirm_cart_agent = LlmAgent(
    instruction=confirm_cart.INSTRUCTION,
    name="confirm_cart_agent",
    description="Confirms the final cart details with the user before payment.",
    model=GEMINI_MODEL,
    tools=[get_cart_details_tool],
)

submit_order_agent = LlmAgent(
    instruction=submit_order.INSTRUCTION,
    name="submit_order_agent",
    description="Collects final details and places the order.",
    model=GEMINI_MODEL,
    tools=[place_order_tool],
)

root_agent = SequentialAgent(
    name="checkout_agent",
    description="Guides the user through the checkout process.",
    sub_agents=[
        confirm_cart_agent,
        submit_order_agent,
    ],
)
