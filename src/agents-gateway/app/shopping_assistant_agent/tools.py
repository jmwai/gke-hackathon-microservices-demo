from __future__ import annotations
from .state import (
    resolve_index_to_product_id,
    resolve_index_to_product_id_for_user,
    get_last_results,
    get_last_results_for_user,
)
from .callbacks import _extract_user_id
import base64
from typing import Any, Dict, List
import logging
import requests
from fastapi import HTTPException
import os

from app.common.config import get_settings
from app.product_discovery_agent.tools import (
    image_vector_search,
    text_vector_search,
)
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext


FRONTEND_BASE = "http://frontend:80"
HTTP_TIMEOUT = 10  # seconds
logger = logging.getLogger("agents.shopping.tools")


# Note: The 'top_k' parameter is added to the signature to match the underlying
# search functions, but the wrappers enforce a fixed value of 5.
def text_search_tool(query: str, top_k: int, filters: Dict[str, Any]):
    s = get_settings()
    k = min(5, s.API_TOP_K_MAX)
    return text_vector_search(query, filters or {}, k)


def image_search_tool(image_base64: str, mime_type: str, top_k: int, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        image_bytes = base64.b64decode(image_base64)
    except Exception:
        raise HTTPException(
            status_code=400, detail="Invalid image_base64 data")
    s = get_settings()
    # Always return 5 (up to API_TOP_K_MAX)
    k = min(5, s.API_TOP_K_MAX)
    return image_vector_search(image_bytes, filters or {}, k)


def add_to_cart(number: int, tool_context: ToolContext) -> Dict[str, Any]:
    """
    Add one product to the user's cart by its ordinal number from the last search.

    Args:
        number: The ordinal number (1-5) of the item to add from the search results.
        tool_context: The execution context, provided by the ADK.
    Returns:
        A normalized cart dict or {"error": "add_to_cart_failed"} on failure.
    """
    # Extract user ID; also check state['user_id'] if callbacks seeded it
    user_id = _extract_user_id(tool_context)
    if not user_id:
        try:
            if hasattr(tool_context, "state") and isinstance(tool_context.state, dict):
                sid = tool_context.state.get("user_id")
                if isinstance(sid, str) and sid:
                    user_id = sid
        except Exception:
            pass
    if not user_id:
        logger.error(
            "add_to_cart: stable user_id not found in context; refusing to write cart")
        return {"error": "user_id_missing", "message": "Session not recognized. Please retry or refresh the page."}
    logger.info("add_to_cart: user=%s requested ordinal=%s", user_id, number)

    # Access session state directly via tool_context.state
    shopping_state = tool_context.state.get("shopping", {})
    last_results = shopping_state.get("last_results", {})
    items = last_results.get("items", [])

    logger.debug(
        "add_to_cart: found %d items in tool_context.state", len(items))

    # Resolve product ID from session state
    product_id = None
    if 1 <= number <= len(items):
        product_id = items[number - 1].get("id")
        logger.debug(
            "add_to_cart: resolved ordinal %d to product_id=%s", number, product_id)

    # Fallback to per-user store if session state is empty
    if not product_id:
        product_id = resolve_index_to_product_id_for_user(user_id, number)

    if not product_id:
        # Compute fallback count for diagnostics
        fallback_lr = get_last_results_for_user(user_id)
        fallback_count = 0
        if isinstance(fallback_lr, dict) and isinstance(fallback_lr.get("items"), list):
            fallback_count = len(fallback_lr.get("items") or [])

        session_count = len(items)
        available = session_count if session_count > 0 else fallback_count
        logger.warning(
            "add_to_cart: could not resolve ordinal=%s for user=%s (session_count=%s fallback_count=%s)",
            number,
            user_id,
            session_count,
            fallback_count,
        )
        if available > 0:
            return {
                "error": f"Could not find item number {number}. I currently have {available} items in your last results. Please choose 1..{available} or search again."
            }
        return {
            "error": f"Could not find item number {number}. I don't have recent search results. Please search for products first."
        }
    quantity = 1

    payload = {"userId": user_id,
               "productId": product_id, "quantity": quantity}
    logger.info(f"Adding to cart: {payload}")
    url = f"{FRONTEND_BASE}/api/cart/add"
    try:
        resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
        logger.debug("add_to_cart POST %s status=%s body=%s",
                     url, resp.status_code, resp.text)
        resp.raise_for_status()
        # Always fetch the fresh cart after adding, to normalize response
        cart_url = f"{FRONTEND_BASE}/api/cart?userId={user_id}"
        cart_resp = requests.get(cart_url, timeout=HTTP_TIMEOUT)
        logger.debug("add_to_cart GET %s status=%s body=%s",
                     cart_url, cart_resp.status_code, cart_resp.text)
        cart_resp.raise_for_status()
        data = cart_resp.json()
        logger.debug("add_to_cart parsed cart json: %s", data)
        return data
    except Exception as e:
        logger.error("add_to_cart failed: %s", e)
        return {"error": "add_to_cart_failed"}


def get_cart(tool_context: ToolContext) -> Dict[str, Any]:
    """
    Return the current user's cart.

    Args:
        tool_context: The ADK ToolContext providing access to session state.
    Returns:
        A normalized cart dict or {"error": "get_cart_failed"} on failure.
    """
    # Extract user ID using the same logic as add_to_cart
    user_id = _extract_user_id(tool_context)
    if not user_id:
        try:
            if hasattr(tool_context, "state") and isinstance(tool_context.state, dict):
                sid = tool_context.state.get("user_id")
                if isinstance(sid, str) and sid:
                    user_id = sid
        except Exception:
            pass
    if not user_id:
        logger.error("get_cart: stable user_id not found in context")
        return {"error": "user_id_missing", "message": "Session not recognized. Please retry or refresh the page."}

    url = f"{FRONTEND_BASE}/api/cart?userId={user_id}"
    logger.info(f"Getting cart for user: {user_id}")
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        logger.debug("get_cart GET %s status=%s body=%s",
                     url, resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()
        logger.debug("get_cart parsed json: %s", data)

        # Check if we got a proper cart response with items
        if isinstance(data, dict) and "items" in data:
            return data
        else:
            # If the API only returned user_id, it means the cart is empty or not found
            # Return a proper empty cart structure
            logger.warning(f"get_cart received incomplete response: {data}")
            return {
                "cart_id": user_id,
                "items": [],
                "total_price": ""
            }
    except Exception as e:
        logger.error("get_cart failed: %s", e)
        return {"error": "get_cart_failed"}


def place_order(tool_context: ToolContext) -> Dict[str, Any]:
    """
    Place an order for the items in the user's cart for the given user.

    This tool hardcodes demo shipping and payment info to mirror the checkout form
    in the frontend. It will fail gracefully if the cart is empty.

    Args:
        user_id: The user identifier (injected by callback or derived by the agent runtime).
        tool_context: The ADK ToolContext providing access to session state if needed.

    Returns:
        A normalized order dict with keys: order_id, tracking_id, status,
        estimated_delivery, message. Returns {"error": "place_order_failed"} on failure.
    """
    try:
        # Ensure there is something in the cart first (source of truth: frontend API)
        user_id = _extract_user_id(tool_context)
        if not user_id:
            try:
                if hasattr(tool_context, "state") and isinstance(tool_context.state, dict):
                    sid = tool_context.state.get("user_id")
                    if isinstance(sid, str) and sid:
                        user_id = sid
            except Exception:
                pass
        if not user_id:
            return {"error": "user_id_missing", "message": "Session not recognized. Please retry or refresh the page."}

        cart_url = f"{FRONTEND_BASE}/api/cart?userId={user_id}"
        cart_resp = requests.get(cart_url, timeout=HTTP_TIMEOUT)
        logger.debug("place_order precheck GET %s status=%s body=%s",
                     cart_url, cart_resp.status_code, cart_resp.text)
        cart_resp.raise_for_status()
        cart_data = cart_resp.json() if cart_resp.text else {}
        items = cart_data.get("items", []) if isinstance(
            cart_data, dict) else []
        if not items:
            return {
                "error": "cart_empty",
                "message": "Your cart is empty. Please add items before placing an order."
            }

        # Demo hardcoded details from cart.html
        DEMO_EMAIL = "someone@example.com"
        DEMO_ADDRESS = "1600 Amphitheatre Parkway, Mountain View, CA 94043, United States"
        DEMO_LAST4 = "0454"

        url = f"{FRONTEND_BASE}/api/checkout"
        payload = {
            "userId": user_id,
            "userDetails": {
                "name": DEMO_EMAIL,  # using email as name surrogate for demo
                "address": DEMO_ADDRESS,
            },
            "paymentInfo": {
                "last4": DEMO_LAST4,
            },
        }
        logger.info("Placing order for user %s", user_id)
        resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
        logger.debug("place_order POST %s status=%s body=%s",
                     url, resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()
        logger.debug("place_order parsed json: %s", data)
        # Normalize expected fields
        return {
            "order_id": data.get("order_id"),
            "tracking_id": data.get("tracking_id"),
            "status": data.get("status"),
            "estimated_delivery": data.get("estimated_delivery"),
            "message": data.get("message"),
        }
    except Exception as e:
        logger.error("place_order failed: %s", e)
        return {"error": "place_order_failed"}


# ADK FunctionTool wrappers
text_search_tool = FunctionTool(text_search_tool)
image_search_tool = FunctionTool(image_search_tool)
add_to_cart_tool = FunctionTool(add_to_cart)
get_cart_tool = FunctionTool(get_cart)
place_order_tool = FunctionTool(place_order)
