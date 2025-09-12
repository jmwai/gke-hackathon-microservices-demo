from __future__ import annotations

import functools
from typing import Any, Dict, Optional

import psycopg2
from psycopg2.pool import SimpleConnectionPool

from .config import get_settings


_pool: Optional[SimpleConnectionPool] = None


def init_pool() -> SimpleConnectionPool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            host=s.DB_HOST,
            port=s.DB_PORT,
            dbname=s.DB_NAME,
            user=s.DB_USER,
            password=s.DB_PASSWORD,
        )
    return _pool


def get_conn():
    return init_pool().getconn()


def put_conn(conn) -> None:
    if _pool is not None:
        _pool.putconn(conn)


def vector_literal(values: list[float]) -> str:
    # pgvector array literal format
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


def health_check() -> Dict[str, Any]:
    """Verify required columns exist; attempt to verify vector dims and ANN indexes.

    Returns a dict with checks; does not raise unless connection fails.
    """
    checks: Dict[str, Any] = {
        "columns": {},
        "dims": {},
        "indexes": [],
    }
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Columns present
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'catalog_items'
                AND column_name IN (
                    'id','name','description','picture','product_image_url',
                    'price_usd_currency_code','price_usd_units','price_usd_nanos',
                    'categories','product_embedding','product_image_embedding'
                )
                """
            )
            cols = {r[0] for r in cur.fetchall()}
            required = {
                'id', 'name', 'description', 'picture', 'product_image_url',
                'price_usd_currency_code', 'price_usd_units', 'price_usd_nanos',
                'categories', 'product_embedding', 'product_image_embedding'
            }
            checks["columns"] = {c: (c in cols) for c in sorted(required)}

            # Try dims via vector_dims() if available
            try:
                cur.execute(
                    "SELECT vector_dims(product_embedding) FROM catalog_items WHERE product_embedding IS NOT NULL LIMIT 1"
                )
                row = cur.fetchone()
                pe_dims = int(row[0]) if row and row[0] is not None else None
            except Exception:
                pe_dims = None
            try:
                cur.execute(
                    "SELECT vector_dims(product_image_embedding) FROM catalog_items WHERE product_image_embedding IS NOT NULL LIMIT 1"
                )
                row = cur.fetchone()
                pie_dims = int(row[0]) if row and row[0] is not None else None
            except Exception:
                pie_dims = None
            checks["dims"] = {
                "product_embedding": pe_dims,
                "product_image_embedding": pie_dims,
            }

            # ANN index presence (ivfflat)
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'catalog_items'
                """
            )
            idx = cur.fetchall()
            checks["indexes"] = [
                {"name": name, "ivfflat": ("USING ivfflat" in definition)}
                for (name, definition) in idx
            ]
    finally:
        put_conn(conn)
    return checks
