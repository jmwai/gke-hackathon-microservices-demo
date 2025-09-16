from __future__ import annotations

import functools
import os
from typing import Any, Dict, Optional
import logging

import psycopg2
from google.cloud import secretmanager
from psycopg2.pool import SimpleConnectionPool

from .config import get_settings

logger = logging.getLogger(__name__)

_pool: Optional[SimpleConnectionPool] = None


def get_secret_payload(project, secret, version="latest") -> str:
    """Get secret from Google Cloud Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    secret_version_name = client.secret_version_path(project, secret, version)
    response = client.access_secret_version(
        request={"name": secret_version_name})
    return response.payload.data.decode("utf-8").strip()


def init_pool():
    global _pool
    if _pool is None:
        # Check if we should use AlloyDB connector
        alloydb_cluster_name = os.environ.get("ALLOYDB_CLUSTER_NAME")
        if alloydb_cluster_name:
            logger.info("Using AlloyDB connector approach")
            _pool = init_alloydb_pool()
        else:
            logger.info("Using direct IP connection approach")
            _pool = init_direct_pool()
    return _pool


def init_direct_pool() -> SimpleConnectionPool:
    """Initialize connection pool using direct IP connection (legacy)."""
    global _pool
    s = get_settings()
    password = s.DB_PASSWORD

    # Check for AlloyDB secret name and fetch from Secret Manager if available
    alloydb_secret_name = os.environ.get("ALLOYDB_SECRET_NAME")
    if alloydb_secret_name:
        try:
            password = get_secret_payload(s.PROJECT_ID, alloydb_secret_name)
        except Exception as e:
            raise RuntimeError(
                f"Failed to access secret: {alloydb_secret_name}") from e

    _pool = SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        host=s.DB_HOST,
        port=s.DB_PORT,
        dbname=s.DB_NAME,
        user=s.DB_USER,
        password=password,
    )
    return _pool


def init_alloydb_pool():
    """Initialize connection pool using AlloyDB connector."""

    project_id = os.environ.get("PROJECT_ID")
    region = os.environ.get("REGION")
    alloydb_cluster_name = os.environ.get("ALLOYDB_CLUSTER_NAME")
    alloydb_instance_name = os.environ.get("ALLOYDB_INSTANCE_NAME")
    alloydb_database_name = os.environ.get("ALLOYDB_DATABASE_NAME")
    alloydb_secret_name = os.environ.get("ALLOYDB_SECRET_NAME")

    if not all([project_id, region, alloydb_cluster_name, alloydb_instance_name, alloydb_database_name, alloydb_secret_name]):
        raise ValueError(
            "Missing required AlloyDB environment variables for password auth")

    # Get password from Secret Manager
    password = get_secret_payload(project_id, alloydb_secret_name)

    # Use the alloydb-python-connector for AlloyDB
    try:
        from google.cloud.alloydb.connector import Connector
        import pg8000

        def getconn():
            # AlloyDB connector expects format: projects/<PROJECT>/locations/<REGION>/clusters/<CLUSTER>/instances/<INSTANCE>
            connection_string = f"projects/{project_id}/locations/{region}/clusters/{alloydb_cluster_name}/instances/{alloydb_instance_name}"

            # Use standard password authentication
            connector = Connector()
            conn = connector.connect(
                connection_string,
                "pg8000",
                user="postgres",
                db=alloydb_database_name,
                password=password,
            )
            return conn

        # Create a custom pool that uses the connector
        return AlloyDBConnectionPool(getconn, minconn=1, maxconn=10)

    except ImportError:
        logger.error(
            "cloud-sql-python-connector not available, falling back to direct connection")
        # Fall back to direct connection if connector not available
        return SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            host="localhost",  # This will fail, but better than crashing
            port=5432,
            dbname=alloydb_database_name,
            user="postgres",
            password=password,
        )


class AlloyDBConnectionPool:
    """Simple connection pool wrapper for AlloyDB connector."""

    def __init__(self, getconn_func, minconn=1, maxconn=10):
        self.getconn_func = getconn_func
        self.minconn = minconn
        self.maxconn = maxconn
        self._connections = []

    def getconn(self):
        """Get a connection from the pool."""
        if self._connections:
            return self._connections.pop()
        return self.getconn_func()

    def putconn(self, conn):
        """Return a connection to the pool."""
        if len(self._connections) < self.maxconn:
            self._connections.append(conn)
        else:
            try:
                conn.close()
            except:
                pass


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
        cur = conn.cursor()
        try:
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
            cur.close()
    finally:
        put_conn(conn)
    return checks
