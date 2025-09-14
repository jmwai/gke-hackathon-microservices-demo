from __future__ import annotations
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import AgentTool
from .prompts import (
    check_return_eligibility,
    customer_support,
    generate_rma,
    verify_purchase,
)
from .tools import (
    initiate_return_tool,
    order_details_tool,
    support_kb_tool,
    track_shipment_tool,
    check_return_eligibility_tool,
)

GEMINI_MODEL = "gemini-2.5-flash"

# Returns Workflow Agents (Deterministic Sequence)
verify_purchase_agent = LlmAgent(
    name="verify_purchase_agent",
    description="First step in the returns workflow. Verifies a user's purchase by fetching their order details.",
    instruction=verify_purchase.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[order_details_tool],
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

# Customer Service Agent (Dispatcher)
root_agent = LlmAgent(
    instruction=customer_support.INSTRUCTION,
    name="customer_service_agent",
    description="Handles customer support inquiries, including order status, returns, and policy questions.",
    model=GEMINI_MODEL,
    tools=[
        order_details_tool,
        support_kb_tool,
        track_shipment_tool,
        AgentTool(returns_workflow_agent),
    ],
)
