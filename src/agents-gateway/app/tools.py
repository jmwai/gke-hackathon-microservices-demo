from __future__ import annotations

import tempfile
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .config import get_settings
from .db import get_conn, put_conn, vector_literal
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
    params: List[Any] = []
    if filters:
        cat = filters.get("category") if isinstance(filters, dict) else None
        if cat:
            where.append("categories ILIKE %s")
            params.append(f"%{cat}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT id, name, description, picture, COALESCE(product_image_url, picture) as product_image_url, "
        f"(product_embedding <=> {qvec}::vector) AS distance "
        "FROM catalog_items"
        + where_sql +
        " ORDER BY distance ASC LIMIT %s"
    )
    params.append(top_k)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            out = []
            for r in cur.fetchall():
                out.append({
                    "product": {
                        "id": r[0], "name": r[1], "description": r[2],
                        "picture": r[3], "product_image_url": r[4]
                    },
                    "distance": float(r[5]),
                    "why": None,
                })
            return out
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
    params: List[Any] = []
    if filters:
        cat = filters.get("category") if isinstance(filters, dict) else None
        if cat:
            where.append("categories ILIKE %s")
            params.append(f"%{cat}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT id, name, description, picture, COALESCE(product_image_url, picture) as product_image_url, "
        f"(product_image_embedding <=> {qvec}::vector) AS distance "
        "FROM catalog_items"
        + where_sql +
        " ORDER BY distance ASC LIMIT %s"
    )
    params.append(top_k)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            out = []
            for r in cur.fetchall():
                out.append({
                    "product": {
                        "id": r[0], "name": r[1], "description": r[2],
                        "picture": r[3], "product_image_url": r[4]
                    },
                    "distance": float(r[5]),
                    "why": None,
                })
            return out
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
    }


def draft_return_intent(order_id: str, items: List[str], reason: str) -> Dict[str, Any]:
    """
    Creates a structured intent for the frontend to process a return.
    Args:
        order_id: The ID of the order to be returned.
        items: A list of item IDs to be returned.
        reason: The reason for the return.
    Returns:
        A dictionary representing the return intent.
    """
    return {"intent": "return", "order_id": order_id, "items": items, "reason": reason}


# ADK FunctionTool wrappers
text_search_tool = FunctionTool(
    fn=text_vector_search,
    description="Performs semantic text search over catalog products to find items based on a description.",
)

image_search_tool = FunctionTool(
    fn=image_vector_search,
    description="Performs visual similarity search to find products that look like a given image.",
)

user_context_tool = FunctionTool(
    fn=get_user_context,
    description="Gets user preferences and context to help with recommendations.",
)

support_kb_tool = FunctionTool(
    fn=search_policy_kb,
    description="Searches the knowledge base for answers to policy questions.",
)

order_details_tool = FunctionTool(
    fn=get_order_details,
    description="Retrieves the details of a customer's order.",
)

draft_return_tool = FunctionTool(
    fn=draft_return_intent,
    description="Creates a structured intent for processing a product return.",
)
