from __future__ import annotations
from .state import resolve_index_to_product_id, resolve_index_to_product_id_for_user
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


FRONTEND_BASE = "http://frontend:80"
HTTP_TIMEOUT = 10  # seconds
logger = logging.getLogger("agents.shopping.tools")


# Note: The 'top_k' parameter is added to the signature to match the underlying
# search functions, but the wrappers enforce a fixed value of 5.
def text_search_tool(query: str, top_k: int, filters: Dict[str, Any]):
    s = get_settings()
    # Always return 5 (up to API_TOP_K_MAX)
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


def add_to_cart(number: int, tool_context: Any) -> Dict[str, Any]:
    """
    Add one product to the user's cart by its ordinal number from the last search.

    Args:
        number: The ordinal number (1-5) of the item to add from the search results.
        tool_context: The execution context, provided by the ADK.
    Returns:
        A normalized cart dict or {"error": "add_to_cart_failed"} on failure.
    """
    user_id = _extract_user_id(tool_context) or "anonymous"
    product_id = resolve_index_to_product_id(tool_context, number)
    # If session is missing (e.g., a new session), fall back to per-user store
    if not product_id:
        product_id = resolve_index_to_product_id_for_user(user_id, number)
    if not product_id:
        return {"error": f"Could not find item number {number}. Please try another search."}
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


def get_cart(user_id: str) -> Dict[str, Any]:
    """
    Return the current user's cart.

    Args:
        user_id: The user identifier.
    Returns:
        A normalized cart dict or {"error": "get_cart_failed"} on failure.
    """
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


def place_order(user_id: str, street_address: str, zip_code: str, city: str, state: str, country: str, credit_card_number: str, credit_card_expiration_month: int, credit_card_expiration_year: int, credit_card_cvv: str) -> Dict[str, Any]:
    """
    Place an order for the items in the user's cart.

    Args:
        user_id: The user identifier.
        street_address: Street address for shipping.
        zip_code: Zip code for shipping.
        city: City for shipping.
        state: State for shipping.
        country: Country for shipping.
        credit_card_number: The 16-digit card number.
        credit_card_expiration_month: The 2-digit card expiration month.
        credit_card_expiration_year: The 4-digit card expiration year.
        credit_card_cvv: The 3-digit card CVV.
    Returns:
        A normalized order dict or {"error": "place_order_failed"} on failure.
    """
    url = f"{FRONTEND_BASE}/api/cart/checkout"
    payload = {
        "userId": user_id,
        "streetAddress": f"{street_address}, {city}, {state}, {zip_code}, {country}",
        "zipCode": zip_code,
        "city": city,
        "state": state,
        "country": country,
        "creditCardNumber": credit_card_number,
        "creditCardExpirationMonth": credit_card_expiration_month,
        "creditCardExpirationYear": credit_card_expiration_year,
        "creditCardCvv": credit_card_cvv,
    }
    logger.info(f"Placing order for user {user_id}")
    try:
        resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
        logger.debug("place_order POST %s status=%s body=%s",
                     url, resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()
        logger.debug("place_order parsed json: %s", data)
        return data
    except Exception as e:
        logger.error("place_order failed: %s", e)
        return {"error": "place_order_failed"}


# ADK FunctionTool wrappers
text_search_tool = FunctionTool(text_search_tool)
image_search_tool = FunctionTool(image_search_tool)
add_to_cart_tool = FunctionTool(add_to_cart)
get_cart_tool = FunctionTool(get_cart)
place_order_tool = FunctionTool(place_order)
