from __future__ import annotations

from typing import Any, Dict, List
from google.adk.tools import FunctionTool


def search_policy_kb(query: str) -> str:
    """
    Searches the knowledge base for answers to customer policy questions.
    Args:
        query: The user's question about store policy.
    Returns:
        The answer from the knowledge base, or a default message if not found.
    """
    # This is a stub. A real implementation would use RAG over policy documents.
    if "return" in query.lower():
        return "You can return items within 30 days for a full refund."
    return "I'm sorry, I couldn't find an answer to that question."


def get_order_details(order_id: str, email: str) -> Dict[str, Any]:
    """
    Retrieves the details for a given order ID and email.
    Args:
        order_id: The unique identifier for the order.
        email: The customer's email address associated with the order.
    Returns:
        A dictionary containing order details.
    """
    # This is a stub. A real implementation would query an order management system.
    print(f"Order: {order_id}, Email: {email}")  # To satisfy linter
    return {
        "order_id": order_id,
        "status": "shipped",
        "items": [{"id": "OLJ-001", "name": "Vintage Sunglasses", "quantity": 1}],
        "tracking_id": "1Z999AA10123456784",
    }


def track_shipment(tracking_id: str) -> Dict[str, Any]:
    """
    Gets the real-time shipping status and estimated delivery date for a given tracking ID.
    Args:
        tracking_id: The unique identifier for the shipment.
    Returns:
        A dictionary with the latest shipping status.
    """
    # This is a stub. A real implementation would call a shipping carrier API.
    print(f"Tracking ID received: {tracking_id}")
    return {
        "tracking_id": tracking_id,
        "status": "in_transit",
        "estimated_delivery_date": "2025-09-18",
        "latest_location": "Facility - USA",
    }


def initiate_return(order_id: str, items: List[str], reason: str) -> Dict[str, Any]:
    """
    Initiates the official return process in the backend system.
    Args:
        order_id: The ID of the order to be returned.
        items: A list of item IDs to be returned.
        reason: The reason for the return.
    Returns:
        A dictionary with the RMA number and shipping label info.
    """
    # This is a stub for a real implementation.
    print(f"Return for order {order_id} ({items}) initiated. Reason: {reason}")
    return {
        "intent": "return_initiated",
        "rma_number": "RMA-12345XYZ",
        "shipping_label_url": "https://shipping.example.com/label/RMA-12345XYZ.pdf",
    }


def check_return_eligibility(order_id: str, items: List[str]) -> Dict[str, Any]:
    """
    Checks if items are eligible for return based on company policy.
    Args:
        order_id: The ID of the order containing the items.
        items: A list of item IDs to check.
    Returns:
        A dictionary confirming eligibility and providing reasons if not.
    """
    # This is a stub. A real implementation would contain business logic.
    print(f"Checking return eligibility for order {order_id}, items: {items}")
    # Simulate one item being ineligible
    if "OLJ-001" in items:
        return {
            "eligible": False,
            "reason": "Item 'OLJ-001' is a final sale item and cannot be returned.",
        }
    return {"eligible": True, "reason": "All items are eligible for return."}


# ADK FunctionTool wrappers
support_kb_tool = FunctionTool(
    search_policy_kb,
)

order_details_tool = FunctionTool(
    get_order_details,
)

track_shipment_tool = FunctionTool(
    track_shipment,
)

initiate_return_tool = FunctionTool(
    initiate_return,
)

check_return_eligibility_tool = FunctionTool(
    check_return_eligibility,
)
