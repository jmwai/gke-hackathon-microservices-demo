from __future__ import annotations
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import AgentTool
from .callbacks import LoggingCallbackHandler, ModerationCallbackHandler
from .tools import (
    text_search_tool,
    image_search_tool,
    user_context_tool,
    support_kb_tool,
    order_details_tool,
    draft_return_tool,
)
from .prompts import (
    boutique_host,
    product_discovery,
    image_search,
    recommendation,
    customer_support,
    verify_purchase,
    check_return_eligibility,
    generate_rma,
)

# Global model configuration
MODEL = "gemini-2.5-pro"

# Instantiate the callback handlers
logging_callback = LoggingCallbackHandler()
moderation_callback = ModerationCallbackHandler()

# Product Discovery Agent (ADK LlmAgent)
# Responds to natural language queries about products.
product_discovery_agent = LlmAgent(
    name="Product Discovery Agent",
    description="Responds to natural language queries about products by using text-based vector search.",
    model=MODEL,
    instructions=product_discovery.INSTRUCTIONS,
    tools=[text_search_tool],
    callbacks=[logging_callback],
)

# Image Search Agent (ADK LlmAgent)
# Finds products based on visual similarity to a provided image.
image_search_agent = LlmAgent(
    name="Image Search Agent",
    description="Finds products based on visual similarity to a provided image using image-based vector search.",
    model=MODEL,
    instructions=image_search.INSTRUCTIONS,
    tools=[image_search_tool],
    callbacks=[logging_callback],
)

# Recommendation Agent (ADK LlmAgent)
# Provides personalized product recommendations.
recommendation_agent = LlmAgent(
    name="Recommendation Agent",
    description="Provides personalized product recommendations by first fetching user context and then searching for relevant products.",
    model=MODEL,
    instructions=recommendation.INSTRUCTIONS,
    tools=[user_context_tool, text_search_tool],
    callbacks=[logging_callback],
)

# Returns Workflow Agents (Deterministic Sequence)
verify_purchase_agent = LlmAgent(
    name="Verify Purchase Agent",
    description="First step in the returns workflow. Verifies a user's purchase by fetching their order details.",
    model=MODEL,
    instructions=verify_purchase.INSTRUCTIONS,
    tools=[order_details_tool],
    callbacks=[logging_callback],
)

check_return_eligibility_agent = LlmAgent(
    name="Check Return Eligibility Agent",
    description="Second step in the returns workflow. Checks if an order is eligible for return based on store policy.",
    model=MODEL,
    instructions=check_return_eligibility.INSTRUCTIONS,
    tools=[support_kb_tool],
    callbacks=[logging_callback],
)

generate_rma_agent = LlmAgent(
    name="Generate RMA Agent",
    description="Final step in the returns workflow. Generates a return merchandise authorization (RMA) intent.",
    model=MODEL,
    instructions=generate_rma.INSTRUCTIONS,
    tools=[draft_return_tool],
    callbacks=[logging_callback],
)

returns_workflow_agent = SequentialAgent(
    name="Returns Workflow Agent",
    description="""
    Handles the end-to-end process for product returns in a deterministic sequence.
    1. Invoke the verify_purchase_agent to confirm the user's order details.
    2. Invoke the check_return_eligibility_agent to ensure the order can be returned.
    3. Invoke the generate_rma_agent to create the final return intent.
    """,
    agents=[
        verify_purchase_agent,
        check_return_eligibility_agent,
        generate_rma_agent,
    ],
    callbacks=[logging_callback],
)

# Customer Support Agent (LlmAgent)
customer_support_agent = LlmAgent(
    name="Customer Support Agent",
    description="""
    Acts as a customer support sub-router.
    1. Answers general policy questions using the knowledge base.
    2. Invokes the returns_workflow_agent for any requests to process a product return.
    """,
    model=MODEL,
    instructions=customer_support.INSTRUCTIONS,
    tools=[
        support_kb_tool,
        AgentTool(
            agent=returns_workflow_agent,
            description="Use for processing product returns.",
        ),
    ],
    callbacks=[logging_callback],
)

# Boutique Host Agent (Router)
# Classifies user intent and routes to the appropriate specialist agent.
boutique_host_agent = LlmAgent(
    name="Boutique Host Agent",
    description="""
    Acts as the main router for the online boutique. It classifies the user's intent and delegates the request to the appropriate specialist agent.
    1. For text search, invokes the product_discovery_agent.
    2. For image search, invokes the image_search_agent.
    3. For recommendations, invokes the recommendation_agent.
    4. For support queries, invokes the customer_support_agent.
    """,
    model=MODEL,
    instructions=boutique_host.INSTRUCTIONS,
    tools=[
        AgentTool(
            agent=product_discovery_agent,
            description="Use for text-based product searches.",
        ),
        AgentTool(
            agent=image_search_agent,
            description="Use for image-based product searches.",
        ),
        AgentTool(
            agent=recommendation_agent,
            description="Use for personalized product recommendations.",
        ),
        AgentTool(
            agent=customer_support_agent,
            description="Use for customer support, returns, and policy questions.",
        ),
    ],
    callbacks=[moderation_callback, logging_callback],
)
