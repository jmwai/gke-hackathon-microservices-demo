from __future__ import annotations
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import AgentTool
from pydantic import BaseModel, Field
from typing import List, Optional
# from .callbacks import LoggingCallbackHandler, ModerationCallbackHandler

from .prompts import (
    boutique_host,
    check_return_eligibility,
    customer_support,
    generate_rma,
    image_search,
    product_discovery,
    recommendation,
    verify_purchase,
    add_to_cart,
    confirm_cart,
    submit_order,
)
from .tools import (
    initiate_return_tool,
    image_search_tool,
    order_details_tool,
    support_kb_tool,
    text_search_tool,
    user_context_tool,
    add_to_cart_tool,
    track_shipment_tool,
    check_return_eligibility_tool,
    get_cart_details_tool,
    place_order_tool,
)

GEMINI_MODEL = "gemini-2.5-flash"

# Instantiate the callback handlers
# logging_callback = LoggingCallbackHandler()
# moderation_callback = ModerationCallbackHandler()


# Pydantic schemas for structured output
class ImageSearchResult(BaseModel):
    id: str = Field(description="Product ID")
    name: str = Field(description="Product name")
    picture: str = Field(description="Product image URL")
    similarity_score: float = Field(description="Visual similarity score")
    description: Optional[str] = Field(description="Product description", default="")
    distance: Optional[float] = Field(description="Search relevance score", default=0.0)


class ImageSearchOutput(BaseModel):
    products: List[ImageSearchResult] = Field(description="Visually similar products")
    search_summary: str = Field(description="Summary of image search results")
    total_results: int = Field(description="Number of results found")

# Product Discovery Agent (ADK LlmAgent)
# Responds to natural language queries about products.
product_discovery_agent = LlmAgent(
    name="product_discovery_agent",
    description="Responds to natural language queries about products by using text-based vector search.",
    instruction=product_discovery.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[text_search_tool],
    # callbacks=[logging_callback],
)

# Image Search Agent (ADK LlmAgent)
# Finds products based on visual similarity to a provided image.
image_search_agent = LlmAgent(
    name="image_search_agent",
    description="Finds products based on visual similarity to a provided image using image-based vector search.",
    instruction=image_search.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[image_search_tool],
    output_schema=ImageSearchOutput,
    output_key="image_search_results",
    # callbacks=[logging_callback],
)

# New specialist agent for adding items to the cart
add_to_cart_agent = LlmAgent(
    instruction=add_to_cart.INSTRUCTION,
    name="add_to_cart_agent",
    description="Adds one or more specified items to the user's shopping cart.",
    model=GEMINI_MODEL,
    tools=[add_to_cart_tool],
)

# Recommendation Agent (ADK LlmAgent)
# Provides personalized product recommendations.
recommendation_agent = LlmAgent(
    name="recommendation_agent",
    description="Provides personalized product recommendations by first fetching user context and then searching for relevant products.",
    instruction=recommendation.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[user_context_tool, text_search_tool],
    # callbacks=[logging_callback],
)

# Returns Workflow Agents (Deterministic Sequence)
verify_purchase_agent = LlmAgent(
    name="verify_purchase_agent",
    description="First step in the returns workflow. Verifies a user's purchase by fetching their order details.",
    instruction=verify_purchase.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[order_details_tool],
    # callbacks=[logging_callback],
)

check_return_eligibility_agent = LlmAgent(
    instruction=check_return_eligibility.INSTRUCTION,
    name="check_return_eligibility_agent",
    description="Checks if an item is eligible for return based on store policy.",
    model=GEMINI_MODEL,
    tools=[check_return_eligibility_tool],
)

generate_rma_agent = LlmAgent(
    instruction=generate_rma.INSTRUCTION,
    name="generate_rma_agent",
    description="Generates a Return Merchandise Authorization (RMA) and shipping label.",
    model=GEMINI_MODEL,
    tools=[initiate_return_tool],
)

returns_workflow_agent = SequentialAgent(
    name="returns_workflow_agent",
    description="A sequential workflow for processing customer returns.",
    sub_agents=[
        verify_purchase_agent,
        check_return_eligibility_agent,
        generate_rma_agent,
    ],
)

customer_support_agent = LlmAgent(
    instruction=customer_support.INSTRUCTION,
    name="customer_support_agent",
    description="Handles customer support inquiries, including order status, returns, and policy questions.",
    model=GEMINI_MODEL,
    tools=[
        order_details_tool,
        support_kb_tool,
        track_shipment_tool,
        AgentTool(returns_workflow_agent),
    ],
)

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

checkout_agent = SequentialAgent(
    name="checkout_agent",
    description="Guides the user through the checkout process.",
    sub_agents=[
        confirm_cart_agent,
        submit_order_agent,
    ],
)

# Boutique Host Agent (Router)
# Classifies user intent and routes to the appropriate specialist agent.
root_agent = LlmAgent(
    name="boutique_agent",
    description="""
    Acts as the main router for the online boutique. It classifies the user's intent and delegates the request to the appropriate specialist agent.
    1. For text search, invokes the product_discovery_agent.
    2. For image search, invokes the image_search_agent.
    3. For recommendations, invokes the recommendation_agent.
    4. For support queries, invokes the customer_support_agent.
    """,
    model=GEMINI_MODEL,
    instruction=boutique_host.INSTRUCTION,
    tools=[
        AgentTool(image_search_agent),
        AgentTool(recommendation_agent),
        AgentTool(customer_support_agent),
        AgentTool(product_discovery_agent),
        AgentTool(add_to_cart_agent),
        AgentTool(checkout_agent),
    ],
    # callbacks=[moderation_callback, logging_callback],
)
