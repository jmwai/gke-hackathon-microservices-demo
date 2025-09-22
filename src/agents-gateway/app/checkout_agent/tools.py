from __future__ import annotations
from typing import Any, Dict
from google.adk.tools import FunctionTool


def get_cart_details(cart_id: str) -> Dict[str, Any]:
    """
    Retrieves the final list of items and total cost for a given cart ID.
    Args:
        cart_id: The unique identifier for the user's cart.
    Returns:
        A dictionary with the cart's contents and total price.
    """
    # This is a stub. A real implementation would call the cart service.
    print(f"Fetching details for cart_id: {cart_id}")
    return {
        "cart_id": cart_id,
        "items": [
            {"product_id": "OLJ-001", "name": "Vintage Sunglasses", "quantity": 1},
            {"product_id": "LSJ-002", "name": "Leather Jacket", "quantity": 1},
        ],
        "total_price": "$250.00",
    }


def place_order(cart_id: str, user_details: Dict, payment_info: Dict) -> Dict[str, Any]:
    """
    Submits the final order to the checkout service.
    Args:
        cart_id: The ID of the cart to be checked out.
        user_details: Dictionary with user's name and address.
        payment_info: Dictionary with mock payment details.
    Returns:
        A dictionary with the final order confirmation details.
    """
    # This is a stub. A real implementation would call the checkout service.
    print(
        f"Placing order for cart {cart_id} with details {user_details} and payment {payment_info}")
    return {
        "order_confirmation": {
            "order_id": "ABC-123-XYZ",
            "status": "success",
            "shipping_tracking_id": "1Z999AA10123456784",
            "message": "Your order has been placed successfully!",
        }
    }


# ADK FunctionTool wrappers
get_cart_details_tool = FunctionTool(
    get_cart_details,
)

place_order_tool = FunctionTool(
    place_order,
)
