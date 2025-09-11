#!/usr/bin/env python3
"""
Vector search tester for Online Boutique

- text_search(query: str) → top-10 rows by product_embedding
- image_search(gcs_url: str) → top-10 rows by product_image_embedding

Requirements:
- pip install google-cloud-aiplatform psycopg2-binary
- gcloud services enable aiplatform.googleapis.com
- gcloud auth application-default login (or set service account ADC)

Environment variables:
- PROJECT_ID, REGION
- DB_HOST, DB_PORT (default 5432), DB_NAME, DB_USER, DB_PASSWORD

Schema expectations (postgres):
- catalog_items(
    id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    picture TEXT,
    product_image_url TEXT,
    product_embedding VECTOR(1408),
    product_image_embedding VECTOR(1408)
  )
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional

import psycopg2  # type: ignore

# Vertex AI
import vertexai  # type: ignore
from vertexai.vision_models import Image, MultiModalEmbeddingModel  # type: ignore


def getenv(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def init_vertex() -> MultiModalEmbeddingModel:
    project = getenv("PROJECT_ID")
    region = getenv("REGION", "europe-west1")
    vertexai.init(project=project, location=region)
    return MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")


def connect_db():
    host = getenv("DB_HOST", "127.0.0.1")
    port = int(getenv("DB_PORT", "5432"))
    dbname = getenv("DB_NAME", "postgres")
    user = getenv("DB_USER", "postgres")
    password = getenv("DB_PASSWORD")
    conn = psycopg2.connect(host=host, port=port,
                            dbname=dbname, user=user, password=password)
    conn.autocommit = True
    return conn


def format_vector_for_pg(values: List[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


def https_to_gcs_uri(https_url: str) -> str:
    prefix = "https://storage.googleapis.com/"
    if https_url.startswith(prefix):
        path = https_url[len(prefix):]
        return f"gs://{path}"
    return https_url


def text_search(query: str) -> List[Dict[str, Any]]:
    model = init_vertex()
    emb = model.get_embeddings(contextual_text=query, dimension=1408)
    qvec = list(emb.text_embedding)
    return _search_impl(qvec, column="product_embedding")


def image_search(image_uri: str) -> List[Dict[str, Any]]:
    model = init_vertex()
    gcs_uri = image_uri if image_uri.startswith(
        "gs://") else https_to_gcs_uri(image_uri)
    img = Image.load_from_file(gcs_uri)
    emb = model.get_embeddings(image=img, dimension=1408)
    qvec = list(emb.image_embedding)
    return _search_impl(qvec, column="product_image_embedding")


def _search_impl(qvec: List[float], *, column: str) -> List[Dict[str, Any]]:
    qlit = format_vector_for_pg(qvec)
    sql = (
        f"SELECT id, name, description, picture, product_image_url, "
        f"       {column} <-> %s::vector AS distance "
        f"FROM catalog_items "
        f"WHERE {column} IS NOT NULL "
        f"ORDER BY {column} <-> %s::vector "
        f"LIMIT 10"
    )
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (qlit, qlit))
            rows = cur.fetchall()
    results: List[Dict[str, Any]] = []
    for r in rows:
        results.append(
            {
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "picture": r[3],
                "product_image_url": r[4],
                "distance": float(r[5]) if r[5] is not None else None,
            }
        )
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Vector search test")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="text query for product_embedding")
    g.add_argument(
        "--image", help="image URL (gs:// or https://storage.googleapis.com/...) for product_image_embedding")
    args = p.parse_args()

    if args.text:
        out = text_search(args.text)
    else:
        out = image_search(args.image)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
