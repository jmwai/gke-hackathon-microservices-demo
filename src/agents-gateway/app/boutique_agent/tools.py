from __future__ import annotations

import tempfile
from typing import Any, Dict, List, Optional
import requests

from fastapi import HTTPException

from app.config import get_settings
from app.db import get_conn, put_conn, vector_literal
from google.adk.tools import FunctionTool


_mme = None
_vertex_inited = False
_embedding_cache = {}


def _ensure_vertex():
    global _mme, _vertex_inited
    if not _vertex_inited:
        try:
            import vertexai  # type: ignore
            from vertexai.vision_models import MultiModalEmbeddingModel  # type: ignore
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Vertex AI SDK not available: {exc}")
        s = get_settings()
        vertexai.init(project=s.PROJECT_ID, location=s.REGION)
        _mme = MultiModalEmbeddingModel.from_pretrained(
            "multimodalembedding@001")
        _vertex_inited = True


def _embed_text_1408(text: str) -> List[float]:
    if text in _embedding_cache:
        return _embedding_cache[text]

    _ensure_vertex()
    # multimodalembedding@001 supports text-only; return 1408-d vector
    try:
        # type: ignore[attr-defined]
        emb = _mme.get_embeddings(text=text, dimension=1408)
        # Some SDK versions return named tuple; support both
        vec = getattr(emb, "text_embedding", None)
        if vec is None:
            vec = emb.values if hasattr(emb, "values") else None
        if vec is None:
            raise RuntimeError("Empty text embedding")

        result = list(vec)
        _embedding_cache[text] = result
        return result
    except TypeError:
        # Fallback if signature differs: try contextual_text
        # type: ignore[attr-defined]
        emb = _mme.get_embeddings(contextual_text=text, dimension=1408)
        vec = getattr(emb, "text_embedding", None)
        if vec is None:
            raise RuntimeError("Empty text embedding (contextual_text)")

        result = list(vec)
        _embedding_cache[text] = result
        return result


def _embed_image_1408_from_bytes(data: bytes) -> List[float]:
    if data in _embedding_cache:
        return _embedding_cache[data]

    _ensure_vertex()
    from vertexai.vision_models import Image  # type: ignore

    with tempfile.NamedTemporaryFile(suffix=".img") as tmp:
        tmp.write(data)
        tmp.flush()
        img = Image.load_from_file(tmp.name)
        # type: ignore[attr-defined]
        emb = _mme.get_embeddings(image=img, dimension=1408)
        vec = getattr(emb, "image_embedding", None)
        if vec is None:
            raise RuntimeError("Empty image embedding")

        result = list(vec)
        _embedding_cache[data] = result
        return result


def text_vector_search(query: str, filters: Optional[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    """
    Performs semantic text search over catalog products.
    Args:
        query: The natural language search query.
        filters: Optional dictionary of filters to apply, e.g. {"category": "sunglasses"}.
        top_k: The maximum number of products to return.
    Returns:
        A list of products matching the search query.
    """
    vec = _embed_text_1408(query)
    qvec = vector_literal(vec)
    where = []
    # Start params list with the vector, which is now parameterized
    params: List[Any] = [qvec]
    if filters:
        cat = filters.get("category") if isinstance(filters, dict) else None
        if cat:
            where.append("categories ILIKE %s")
            params.append(f"%{cat}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT id, name, description, picture, COALESCE(product_image_url, picture) as product_image_url, "
        "(product_embedding <=> %s::vector) AS distance "  # Use %s placeholder
        "FROM catalog_items"
        + where_sql +
        " ORDER BY distance ASC LIMIT %s"
    )
    params.append(top_k)

    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            out = []
            for r in cur.fetchall():
                out.append({
                    "id": r[0],
                    "name": r[1],
                    "picture": r[3],
                    "product_image_url": r[4],
                    "distance": float(r[5]),
                })
            return out
        finally:
            cur.close()
    finally:
        put_conn(conn)


def image_vector_search(image_bytes: bytes, filters: Optional[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    """
    Performs visual similarity search for products based on an image.
    Args:
        image_bytes: The raw bytes of the image to search with.
        filters: Optional dictionary of filters to apply, e.g. {"category": "sunglasses"}.
        top_k: The maximum number of products to return.
    Returns:
        A list of visually similar products.
    """
    vec = _embed_image_1408_from_bytes(image_bytes)
    qvec = vector_literal(vec)
    where = []
    # Start params list with the vector, which is now parameterized
    params: List[Any] = [qvec]
    if filters:
        cat = filters.get("category") if isinstance(filters, dict) else None
        if cat:
            where.append("categories ILIKE %s")
            params.append(f"%{cat}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT id, name, description, picture, COALESCE(product_image_url, picture) as product_image_url, "
        "(product_image_embedding <=> %s::vector) AS distance "  # Use %s placeholder
        "FROM catalog_items"
        + where_sql +
        " ORDER BY distance ASC LIMIT %s"
    )
    params.append(top_k)

    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            out = []
            for r in cur.fetchall():
                out.append({
                    "id": r[0],
                    "name": r[1],
                    "picture": r[3],
                    "product_image_url": r[4],
                    "distance": float(r[5]),
                })
            return out
        finally:
            cur.close()
    finally:
        put_conn(conn)


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


def add_items_to_cart(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Adds one or more items to the user's shopping cart.

    Args:
        items: A list of products to add. Each product should be a
               dictionary with "product_id" and "quantity" keys.
               Example: [{"product_id": "OLJ-001", "quantity": 1}]

    Returns:
        A dictionary representing the updated state of the cart.
    """
    # This is a placeholder for the actual API call to the cart service.
    # We would replace this with the correct gRPC or HTTP call.
    cart_service_url = "http://cartservice:7070/cart"  # Example URL
    try:
        response = requests.post(cart_service_url, json={"items": items})
        response.raise_for_status()  # Raise an exception for bad status codes
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Could not connect to cart service: {e}"}


# ADK FunctionTool wrappers
text_search_tool = FunctionTool(
    text_vector_search,
)

image_search_tool = FunctionTool(
    image_vector_search,
)

user_context_tool = FunctionTool(
    get_user_context,
)

support_kb_tool = FunctionTool(
    search_policy_kb,
)

order_details_tool = FunctionTool(
    get_order_details,
)

initiate_return_tool = FunctionTool(
    initiate_return,
)

add_to_cart_tool = FunctionTool(
    add_items_to_cart,
)

track_shipment_tool = FunctionTool(
    track_shipment,
)

check_return_eligibility_tool = FunctionTool(
    check_return_eligibility,
)

get_cart_details_tool = FunctionTool(
    get_cart_details,
)

place_order_tool = FunctionTool(
    place_order,
)
