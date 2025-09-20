from __future__ import annotations

from typing import Any, Dict
from google.adk.tools import FunctionTool
import requests
import os
import json
import logging
from typing import List

# To avoid code duplication, we import the search tool from the product discovery agent.
# In a real-world scenario with more complex dependencies, a shared `common/tools.py`
# might be a better pattern. For now, this direct import is clean and efficient.
from app.product_discovery_agent.tools import text_vector_search, image_vector_search
import base64
from app.common.config import get_settings


def get_user_context(user_key: str) -> Dict[str, Any]:
    """
    Retrieves user preferences and context based on a user key.
    In a real implementation, this would fetch data from a session state store
    or a user profile database.
    Args:
        user_key: A unique identifier for the user.
    Returns:
        A dictionary of user preferences, e.g., {'filters': {'category': 'vintage'}}
    """
    # This is a stub. In a real system, you would look up the user_key in a
    # session or memory store (e.g., Redis, Memorystore, or ADK Memory).
    print(f"User key received: {user_key}")  # To satisfy linter
    return {"filters": {"category": "vintage"}}


user_context_tool = FunctionTool(
    get_user_context,
)


# ===================== Cart & Checkout (Option A: call frontend HTTP) =====================

FRONTEND_BASE = os.getenv("FRONTEND_BASE_URL", "http://frontend:80")
HTTP_TIMEOUT = 8
logger = logging.getLogger("agents.shopping.tools")


def add_to_cart(user_id: str, product_id: str, quantity: int) -> Dict[str, Any]:
    payload = {"userId": user_id,
               "productId": product_id, "quantity": quantity if isinstance(quantity, int) and quantity > 0 else 1}
    logger.info(f"Adding to cart: {payload}")
    url = f"{FRONTEND_BASE}/api/cart/add"
    try:
        resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("add_to_cart failed: %s", e)
        return {"error": "add_to_cart_failed"}


def get_cart(user_id: str) -> Dict[str, Any]:
    url = f"{FRONTEND_BASE}/api/cart?userId={user_id}"
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("get_cart failed: %s", e)
        return {"error": "get_cart_failed"}


def place_order(user_id: str, name: str, address: str, last4: str) -> Dict[str, Any]:
    url = f"{FRONTEND_BASE}/api/checkout"
    payload = {
        "userId": user_id,
        "userDetails": {"name": name, "address": address},
        "paymentInfo": {"last4": last4 or "4242"},
    }
    try:
        resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("place_order failed: %s", e)
        return {"error": "place_order_failed"}


add_to_cart_tool = FunctionTool(add_to_cart)
get_cart_tool = FunctionTool(get_cart)
place_order_tool = FunctionTool(place_order)


# ===================== Search Wrapper (stable tool name) =====================

def text_search_tool(query: str, top_k: int, filters: Dict[str, Any]):
    s = get_settings()
    k = max(1, min(int(top_k), s.API_TOP_K_MAX))
    return text_vector_search(query, filters or {}, k)


text_search_tool = FunctionTool(text_search_tool)


def image_search_tool(image_base64: str, mime_type: str, top_k: int, filters: Dict[str, Any]):
    try:
        image_bytes = base64.b64decode(image_base64)
    except Exception:
        return []
    s = get_settings()
    k = max(1, min(int(top_k), s.API_TOP_K_MAX))
    return image_vector_search(image_bytes, filters or {}, k)


image_search_tool = FunctionTool(image_search_tool)
