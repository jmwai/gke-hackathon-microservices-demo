from __future__ import annotations

import tempfile
import logging
from timeit import default_timer as timer
from typing import Any, Dict, List, Optional
import base64
from decimal import Decimal

from fastapi import HTTPException

from app.common.config import get_settings
from app.common.db import get_conn, put_conn, vector_literal
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
    start_time = timer()
    result_count = 0
    out: List[Dict[str, Any]] = []
    print(
        f"DEBUG: text_vector_search called with query='{query}', filters={filters}, top_k={top_k}")
    try:
        vec = _embed_text_1408(query)
        qvec = vector_literal(vec)
        where = []
        # Start params list with the vector, which is now parameterized
        params: List[Any] = [qvec]
        if filters:
            cat = filters.get("category") if isinstance(
                filters, dict) else None
            if cat:
                where.append("categories ILIKE %s")
                params.append(f"%{cat}%")
        where.append("product_embedding IS NOT NULL")
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        sql = (
            "SELECT id, name, description, picture, COALESCE(product_image_url, picture) as product_image_url, "
            "COALESCE((price_usd_units + (price_usd_nanos/1000000000.0))::float8, 0.0) AS price, "
            "(product_embedding <=> %s::vector) AS distance "
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
                for r in cur.fetchall():
                    price_val = r[5]
                    if isinstance(price_val, Decimal):
                        price_num = float(price_val)
                    elif isinstance(price_val, (int, float)):
                        price_num = float(price_val)
                    else:
                        try:
                            price_num = float(
                                price_val) if price_val is not None else 0.0
                        except Exception:
                            price_num = 0.0

                    out.append({
                        "id": r[0],
                        "name": r[1],
                        "description": r[2],
                        "picture": r[3],
                        "product_image_url": r[4],
                        "price": price_num,
                        "distance": float(r[6]),
                    })
                    result_count += 1
            finally:
                cur.close()
        finally:
            put_conn(conn)
    finally:
        elapsed_ms = (timer() - start_time) * 1000.0
        logging.getLogger("agents.vector_search").info(
            "text_vector_search completed in %.2f ms (top_k=%s, results=%s)",
            elapsed_ms,
            top_k,
            result_count,
        )
        print(
            f"DEBUG: text_vector_search returning {result_count} results: {out}")
    return out


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
                    "description": r[2],
                    "picture": r[3],
                    "product_image_url": r[4],
                    "distance": float(r[5]),
                })
            return out
        finally:
            cur.close()
    finally:
        put_conn(conn)


def init_vertex():
    _ensure_vertex()


# ADK FunctionTool wrappers with defaults and clamping (Product Discovery wants 20)
def pd_text_search(query: str, filters: Dict[str, Any], top_k: int) -> List[Dict[str, Any]]:
    s = get_settings()
    k = max(1, min(int(top_k), s.API_TOP_K_MAX))
    return text_vector_search(query, filters or {}, k)


def pd_image_search(image_base64: str, mime_type: str, top_k: int, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Decode base64 string to bytes; mime_type is currently unused but kept for schema clarity
    try:
        image_bytes = base64.b64decode(image_base64)
    except Exception:
        raise HTTPException(
            status_code=400, detail="Invalid image_base64 data")
    s = get_settings()
    k = max(1, min(int(top_k), s.API_TOP_K_MAX))
    return image_vector_search(image_bytes, filters or {}, k)


text_search_tool = FunctionTool(pd_text_search)
image_search_tool = FunctionTool(pd_image_search)
