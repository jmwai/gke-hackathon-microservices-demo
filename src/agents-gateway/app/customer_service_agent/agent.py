from __future__ import annotations
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import AgentTool
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
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


class OrderInfo(BaseModel):
    order_id: str = Field(description="Order ID")
    status: str = Field(description="Order status")
    items: List[Dict[str, Any]] = Field(description="Order items")
    tracking_id: Optional[str] = Field(
        description="Tracking ID if available", default=None)


class ShippingInfo(BaseModel):
    tracking_id: str = Field(description="Shipment tracking ID")
    status: str = Field(description="Current shipping status")
    estimated_delivery_date: Optional[str] = Field(
        description="Estimated delivery date", default=None)
    latest_location: Optional[str] = Field(
        description="Latest known location", default=None)


class PolicyInfo(BaseModel):
    query: str = Field(description="Original policy question")
    answer: str = Field(description="Policy answer from knowledge base")
    related_policies: Optional[List[str]] = Field(
        description="Related policies", default=None)


class ReturnInfo(BaseModel):
    rma_number: Optional[str] = Field(
        description="Return merchandise authorization number", default=None)
    shipping_label_url: Optional[str] = Field(
        description="Return shipping label URL", default=None)
    eligibility_status: Optional[str] = Field(
        description="Return eligibility status", default=None)
    workflow_step: Optional[str] = Field(
        description="Current step in return workflow", default=None)


class SupportResult(BaseModel):
    inquiry_type: str = Field(
        description="Type of support inquiry (order_status, shipping, policy, return)")
    resolution_status: str = Field(
        description="Status of resolution (resolved, in_progress, escalated)")
    message: str = Field(description="Main response message")
    order_info: Optional[OrderInfo] = Field(
        description="Order details if applicable", default=None)
    shipping_info: Optional[ShippingInfo] = Field(
        description="Shipping details if applicable", default=None)
    policy_info: Optional[PolicyInfo] = Field(
        description="Policy information if applicable", default=None)
    return_info: Optional[ReturnInfo] = Field(
        description="Return process information if applicable", default=None)
    next_steps: Optional[List[str]] = Field(
        description="Recommended next steps for customer", default=None)


class CustomerServiceOutput(BaseModel):
    support_result: SupportResult = Field(
        description="Customer service response")
    success: bool = Field(
        description="Whether the inquiry was successfully handled")
    timestamp: Optional[str] = Field(
        description="Response timestamp", default=None)


# Returns Workflow Schemas
class VerificationResult(BaseModel):
    order_found: bool = Field(description="Whether order was found")
    order_details: Optional[Dict[str, Any]] = Field(
        description="Order information", default=None)
    verification_status: str = Field(
        description="Verification status (verified, failed, pending)")
    next_step: str = Field(description="Next step in workflow")


class EligibilityResult(BaseModel):
    eligible: bool = Field(description="Whether items are eligible for return")
    reason: str = Field(
        description="Eligibility reason or rejection explanation")
    policy_details: Optional[str] = Field(
        description="Relevant policy information", default="")
    workflow_step: str = Field(description="Current workflow step")


class RMAResult(BaseModel):
    rma_number: str = Field(
        description="Return merchandise authorization number")
    shipping_label_url: Optional[str] = Field(
        description="Return shipping label URL", default="")
    instructions: List[str] = Field(description="Return instructions")
    status: str = Field(description="RMA generation status")


class WorkflowOutput(BaseModel):
    workflow_step: str = Field(description="Current workflow step")
    success: bool = Field(description="Whether the step was successful")
    result: Any = Field(description="Step-specific result data")


# Returns Workflow Agents (Deterministic Sequence)
verify_purchase_agent = LlmAgent(
    name="verify_purchase_agent",
    description="First step in the returns workflow. Verifies a user's purchase by fetching their order details.",
    instruction=verify_purchase.INSTRUCTION,
    model=GEMINI_MODEL,
    tools=[order_details_tool],
    output_schema=WorkflowOutput,
    output_key="verification_result",
)

check_return_eligibility_agent = LlmAgent(
    instruction=check_return_eligibility.INSTRUCTION,
    name="check_return_eligibility_agent",
    description="Checks if an item is eligible for return based on store policy.",
    model=GEMINI_MODEL,
    tools=[check_return_eligibility_tool],
    output_schema=WorkflowOutput,
    output_key="eligibility_result",
)

generate_rma_agent = LlmAgent(
    instruction=generate_rma.INSTRUCTION,
    name="generate_rma_agent",
    description="Generates a Return Merchandise Authorization (RMA) and shipping label.",
    model=GEMINI_MODEL,
    tools=[initiate_return_tool],
    output_schema=WorkflowOutput,
    output_key="rma_result",
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
    output_schema=CustomerServiceOutput,
    output_key="customer_service_response"
)
