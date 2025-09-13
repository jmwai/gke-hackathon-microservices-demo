from __future__ import annotations
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import AgentTool
# from .callbacks import LoggingCallbackHandler, ModerationCallbackHandler
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
GEMINI_MODEL = "gemini-2.5-pro"

# Instantiate the callback handlers
# logging_callback = LoggingCallbackHandler()
# moderation_callback = ModerationCallbackHandler()

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
    # callbacks=[logging_callback],
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
    name="check_return_eligibility_agent",
    description="Second step in the returns workflow. Checks if an order is eligible for return based on store policy.",
    instruction=check_return_eligibility.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[support_kb_tool],
    # callbacks=[logging_callback],
)

generate_rma_agent = LlmAgent(
    name="generate_rma_agent",
    description="Final step in the returns workflow. Generates a return merchandise authorization (RMA) intent.",
    instruction=generate_rma.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[draft_return_tool],
    # callbacks=[logging_callback],
)

returns_workflow_agent = SequentialAgent(
    name="returns_workflow_agent",
    description="""
    Handles the end-to-end process for product returns in a deterministic sequence.
    1. Invoke the verify_purchase_agent to confirm the user's order details.
    2. Invoke the check_return_eligibility_agent to ensure the order can be returned.
    3. Invoke the generate_rma_agent to create the final return intent.
    """,
    sub_agents=[
        verify_purchase_agent,
        check_return_eligibility_agent,
        generate_rma_agent,
    ],
    # callbacks=[logging_callback],
)

# Customer Support Agent (LlmAgent)
customer_support_agent = LlmAgent(
    name="customer_support_agent",
    description="""
    Acts as a customer support sub-router.
    1. Answers general policy questions using the knowledge base.
    2. Invokes the returns_workflow_agent for any requests to process a product return.
    """,
    model=GEMINI_MODEL,
    instruction=customer_support.INSTRUCTION,
    tools=[
        support_kb_tool,
        AgentTool(
            agent=returns_workflow_agent,
        ),
    ],
    # callbacks=[logging_callback],
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
        AgentTool(
            agent=product_discovery_agent,
        ),
        AgentTool(
            agent=image_search_agent,
        ),
        AgentTool(
            agent=recommendation_agent,
        ),
        AgentTool(
            agent=customer_support_agent,
        ),
    ],
    # callbacks=[moderation_callback, logging_callback],
)
