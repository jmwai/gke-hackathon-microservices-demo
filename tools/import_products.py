#!/usr/bin/env python3
"""
Flipkart → Online Boutique importer

Features
- Modes:
  - local: generate src/productcatalogservice/products.json (no GCP)
  - gcp: upload images to GCS, upsert products into AlloyDB, create text + image embeddings

Assumptions
- Region: europe-west1
- Image embeddings: Vertex AI multimodalembedding@001 (vector size 1408)
- Text embeddings: In-DB google_ml_integration: embedding('textembedding-gecko@003', ...)

Usage examples
  Local mode (writes 10 products, downloads images locally, updates products.json):
    python tools/import_products.py \
      --mode local \
      --input data/flipkart_fashion_products_dataset.json \
      --bucket boutique-demo \  # ignored in local mode
      --fx-rate 88

  GCP mode (GCS + AlloyDB + embeddings):
    python tools/import_products.py \
      --mode gcp \
      --input data/flipkart_fashion_products_dataset.json \
      --sample-size 1000 \
      --bucket online-boutique \
      --fx-rate 88 \
      --project gemini-adk-vertex-2025 \
      --region europe-west1 \
      --db-host 34.14.6.17 \
      --db-port 5432 \
      --db-name products \
      --db-user postgres \
      --db-password <PASSWORD>
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Flipkart → Online Boutique importer")
    p.add_argument("--mode", choices=["local", "gcp"], required=True)
    p.add_argument("--input", required=True,
                   help="Path to flipkart_fashion_products_dataset.json")
    p.add_argument("--sample-size", type=int, default=1000)
    p.add_argument("--bucket", required=True,
                   help="GCS bucket name (e.g., boutique-demo)")
    p.add_argument("--fx-rate", type=float, default=88.0,
                   help="INR→USD fixed FX rate")
    # GCP/Vertex
    p.add_argument(
        "--project", help="GCP project id (required for --mode gcp)")
    p.add_argument("--region", default="europe-west1",
                   help="Vertex/AlloyDB region")
    # DB
    p.add_argument("--db-host", help="AlloyDB host/ip")
    p.add_argument("--db-port", type=int, default=5432)
    p.add_argument("--db-name", default="products")
    p.add_argument("--db-user", default="postgres")
    p.add_argument("--db-password")
    # Behavior
    p.add_argument("--seed", type=int, help="Random seed for sampling")
    p.add_argument("--allow-remote-picture-in-local", action="store_true",
                   help="In local mode, set picture to remote Flipkart URL instead of GCS URL")
    # Soft per-category cap controls (applied in gcp mode)
    p.add_argument("--max-per-category", type=int, default=None,
                   help="Base per-category cap; default=max(5, sample_size//20)")
    p.add_argument("--cap-relax-start", type=float, default=0.5,
                   help="Fraction of target at which to start relaxing cap (default 0.5)")
    p.add_argument("--cap-relax-factor", type=float, default=1.5,
                   help="Overflow multiplier after relax start (default 1.5)")
    p.add_argument("--cap-relax-final", type=float, default=0.9,
                   help="Fraction of target at which to ignore caps (default 0.9)")
    return p.parse_args()


def try_import_ijson() -> Any:
    try:
        import ijson  # type: ignore
        return ijson
    except Exception:
        return None


def stream_flipkart_items(path: str, limit: Optional[int], seed: Optional[int]) -> Iterable[Dict[str, Any]]:
    """Stream objects from a massive JSON array using ijson; fallback to naive if small.

    The Flipkart file is expected to be a single large JSON array of product objects.
    """
    ijson = try_import_ijson()
    if ijson is None:
        _log("ijson not installed; attempting to load first N items with standard json (may be memory-heavy)")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get(
            "items") or data.get("products") or []
        if not isinstance(items, list):
            raise RuntimeError(
                "Input JSON does not appear to be an array of product objects")
        # Yield up to limit, or all if limit is None
        iterable = items if limit is None else items[:limit]
        for obj in iterable:
            yield obj
        return

    # Streaming parse with ijson
    with open(path, "rb") as f:
        parser = ijson.items(f, "item")  # top-level array items
        if seed is not None:
            random.seed(seed)
        count = 0
        for obj in parser:
            # Yield until limit reached; simple first-N selection
            # Replace with reservoir sampling for diversity if desired
            yield obj
            count += 1
            if limit is not None and count >= limit:
                break


def normalize_string(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def parse_price_inr_to_usd(price_str: Optional[str], fx_rate: float) -> Optional[Tuple[int, int]]:
    if not price_str:
        return None
    # Remove commas and non-numeric chars except dot
    cleaned = "".join(ch for ch in price_str if (ch.isdigit() or ch == "."))
    if not cleaned:
        return None
    try:
        inr = float(cleaned)
        usd = inr / fx_rate
        units = int(math.floor(usd))
        nanos = int(round((usd - units) * 1_000_000_000))
        # Normalize potential rounding to 1e9
        if nanos == 1_000_000_000:
            units += 1
            nanos = 0
        return units, nanos
    except Exception:
        return None


def derive_categories(category: Optional[str], sub_category: Optional[str]) -> List[str]:
    cats: List[str] = []
    if category:
        cats.append(str(category).strip().lower())
    if sub_category:
        sc = str(sub_category).strip().lower()
        if sc and sc not in cats:
            cats.append(sc)
    return cats


def choose_primary_image(images: Any) -> Optional[str]:
    if isinstance(images, list) and images:
        return images[0]
    return None


def gcs_https_url(bucket: str, object_name: str) -> str:
    return f"https://storage.googleapis.com/{bucket}/{object_name}"


def gcs_uri(bucket: str, object_name: str) -> str:
    return f"gs://{bucket}/{object_name}"


def https_to_gcs_uri(https_url: str) -> str:
    """Convert https://storage.googleapis.com/<bucket>/<object> to gs://<bucket>/<object>."""
    prefix = "https://storage.googleapis.com/"
    if https_url.startswith(prefix):
        path = https_url[len(prefix):]
        return f"gs://{path}"
    return https_url


def slugify_name(name: Optional[str]) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"[\s-]+", "-", name).strip("-")
    return name or "product"


def build_product_record(
    obj: Dict[str, Any], *, picture_url: str, price_usd: Tuple[int, int], categories: List[str], description_text: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "id": obj.get("pid") or obj.get("_id"),
        "name": normalize_string(obj.get("title")) or "",
        "description": (description_text or (normalize_string(obj.get("description")) or "")),
        "picture": picture_url,
        "priceUsd": {
            "currencyCode": "USD",
            "units": price_usd[0],
            "nanos": price_usd[1],
        },
        "categories": categories,
    }


# -------------------- GCP utilities --------------------

def init_vertex(project: str, region: str) -> None:
    try:
        import vertexai  # type: ignore
        vertexai.init(project=project, location=region)
    except Exception as exc:
        raise RuntimeError(f"Failed to init Vertex AI SDK: {exc}")


def get_text_embedding_vectors(texts: List[str]) -> List[List[float]]:
    """Use in-DB embedding for text. Kept here for optional fallback.

    We prefer the in-DB google_ml_integration embedding() function for bulk updates.
    This function can be used as a client-side fallback if needed.
    """
    import vertexai  # type: ignore
    from vertexai.language_models import TextEmbeddingModel  # type: ignore

    model = TextEmbeddingModel.from_pretrained("textembedding-gecko@003")
    # API accepts up to 96 inputs per call typically; batch if needed
    result = model.get_embeddings(texts)
    return [e.values for e in result]


def get_image_embedding_vector(image_gcs_uri: str) -> List[float]:
    from vertexai.vision_models import MultiModalEmbeddingModel, Image  # type: ignore

    model = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")
    image = Image.load_from_uri(image_gcs_uri)
    emb = model.get_embeddings(image=image)
    # emb.image_embedding is the vector
    return emb.image_embedding.values


def ensure_gcs_object(bucket: str, object_name: str, src_url: str) -> str:
    """Download from src_url and upload to GCS at bucket/object_name. Returns HTTPS URL.
    """
    from google.cloud import storage  # type: ignore
    import requests  # type: ignore

    client = storage.Client()
    bkt = client.bucket(bucket)
    blob = bkt.blob(object_name)

    # Stream download then upload
    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(object_name)[1] or ".jpg") as tmp:
        resp = requests.get(src_url, timeout=30)
        resp.raise_for_status()
        tmp.write(resp.content)
        tmp.flush()
        blob.upload_from_filename(tmp.name, content_type="image/jpeg")

    # With Uniform bucket-level access, rely on bucket IAM for public access
    return gcs_https_url(bucket, object_name)


def connect_db(args: argparse.Namespace):
    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(
            host=args.db_host,
            port=args.db_port,
            dbname=args.db_name,
            user=args.db_user,
            password=args.db_password,
        )
        conn.autocommit = True
        return conn
    except Exception as exc:
        raise RuntimeError(f"Failed to connect to AlloyDB: {exc}")


def product_exists(conn, pid: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM catalog_items WHERE id = %s LIMIT 1", (pid,))
        return cur.fetchone() is not None


def upsert_product(conn, row: Dict[str, Any]) -> None:
    sql = (
        "INSERT INTO catalog_items "
        "(id, name, description, picture, product_image_url, "
        " price_usd_currency_code, price_usd_units, price_usd_nanos, "
        " categories, metadata, "
        " product_embedding, embed_model, product_image_embedding, image_embed_model) "
        "VALUES (%(id)s, %(name)s, %(description)s, %(picture)s, %(product_image_url)s, "
        "        'USD', %(price_units)s, %(price_nanos)s, %(categories)s, %(metadata)s, "
        "        %(text_vec)s, %(text_model)s, %(image_vec)s, %(image_model)s) "
        "ON CONFLICT (id) DO UPDATE SET "
        " name=EXCLUDED.name, description=EXCLUDED.description, picture=EXCLUDED.picture, "
        " product_image_url=EXCLUDED.product_image_url, "
        " price_usd_currency_code='USD', price_usd_units=EXCLUDED.price_usd_units, "
        " price_usd_nanos=EXCLUDED.price_usd_nanos, categories=EXCLUDED.categories, "
        " metadata=EXCLUDED.metadata, "
        " product_embedding=COALESCE(EXCLUDED.product_embedding, catalog_items.product_embedding), "
        " embed_model=COALESCE(EXCLUDED.embed_model, catalog_items.embed_model), "
        " product_image_embedding=COALESCE(EXCLUDED.product_image_embedding, catalog_items.product_image_embedding), "
        " image_embed_model=COALESCE(EXCLUDED.image_embed_model, catalog_items.image_embed_model)"
    )
    payload = {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "picture": row["picture"],
        "product_image_url": row.get("product_image_url"),
        "price_units": row["priceUsd"]["units"],
        "price_nanos": row["priceUsd"]["nanos"],
        "categories": ",".join(row["categories"]) if row.get("categories") else None,
        "metadata": json.dumps(row.get("metadata") or {}),
        "text_vec": row.get("text_vec"),
        "text_model": row.get("text_model"),
        "image_vec": row.get("image_vec"),
        "image_model": row.get("image_model"),
    }
    with conn.cursor() as cur:
        cur.execute(sql, payload)


def run_text_embeddings_in_db(conn) -> None:
    sql = (
        "UPDATE catalog_items "
        "SET product_embedding = embedding('textembedding-gecko@003', CONCAT_WS(' ', name, description)), "
        "    embed_model='textembedding-gecko@003' "
        "WHERE product_embedding IS NULL"
    )
    with conn.cursor() as cur:
        cur.execute(sql)


def format_vector_for_pg(values: List[float]) -> str:
    # pgvector accepts array-literal-like format: '[v1,v2,...]'
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


def update_image_embedding(conn, pid: str, vector: List[float]) -> None:
    sql = (
        "UPDATE catalog_items SET product_image_embedding = %s, image_embed_model = 'multimodalembedding@001' "
        "WHERE id = %s"
    )
    vec_literal = format_vector_for_pg(vector)
    with conn.cursor() as cur:
        cur.execute(sql, (vec_literal, pid))


def fetch_products_missing_image_embeddings(conn, batch_size: int = 100) -> List[Tuple[str, str]]:
    sql = (
        "SELECT id, product_image_url FROM catalog_items "
        "WHERE product_image_embedding IS NULL AND product_image_url IS NOT NULL "
        "LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (batch_size,))
        return [(r[0], r[1]) for r in cur.fetchall()]


# -------------------- Main flows --------------------

def run_local(args: argparse.Namespace) -> None:
    _log("Starting local mode: generating products.json with 10 products and local images (diverse categories)")
    out_path = os.path.join("src", "productcatalogservice", "products.json")
    local_img_dir = os.path.join(
        "src", "frontend", "static", "img", "products")
    os.makedirs(local_img_dir, exist_ok=True)

    products: List[Dict[str, Any]] = []
    # Always limit to 10 for local mode
    local_limit = 10
    # scan more to improve diversity
    scan_limit = 10000
    max_per_category = 2
    category_counts: Dict[str, int] = {}

    import requests  # type: ignore

    for obj in stream_flipkart_items(args.input, scan_limit, args.seed):
        pid = obj.get("pid") or obj.get("_id")
        title = normalize_string(obj.get("title"))
        desc = normalize_string(obj.get("description"))
        price_tuple = parse_price_inr_to_usd(normalize_string(obj.get(
            "selling_price")) or normalize_string(obj.get("actual_price")), args.fx_rate)
        primary_img = choose_primary_image(obj.get("images"))
        if not pid or not title or not desc or not price_tuple or not primary_img:
            reasons = []
            if not pid:
                reasons.append("missing id")
            if not title:
                reasons.append("missing title")
            if not desc:
                reasons.append("missing description")
            if not price_tuple:
                reasons.append("missing/invalid price")
            if not primary_img:
                reasons.append("no image")
            _log(f"Skip local: reasons={'; '.join(reasons)}")
            continue

        cats = derive_categories(normalize_string(
            obj.get("category")), normalize_string(obj.get("sub_category")))

        # Category diversity using sub-category (fallback to top-level)
        sub_cat = cats[1] if len(cats) > 1 else (
            cats[0] if cats else "uncategorized")
        if category_counts.get(sub_cat, 0) >= max_per_category:
            _log(f"Skip local: category cap reached for sub_cat '{sub_cat}'")
            continue

        # Download and save image locally under frontend static assets
        slug = slugify_name(title)
        local_filename = f"{slug}.jpg"
        local_path = os.path.join(local_img_dir, local_filename)
        try:
            _log(
                f"Downloading image (local) id={pid} name='{title}' url={primary_img}")
            resp = requests.get(primary_img, timeout=30)
            resp.raise_for_status()
            with open(local_path, "wb") as imgf:
                imgf.write(resp.content)
            _log(f"Saved image to {local_path}")
        except Exception as exc:
            _log(f"WARN: failed to download image for {pid}: {exc}")
            continue

        # Frontend serves /static/... from src/frontend/static
        picture_url = f"/static/img/products/{local_filename}"

        combined_desc = f"{title}. {desc}" if desc else title
        record = build_product_record(
            obj, picture_url=picture_url, price_usd=price_tuple, categories=cats, description_text=combined_desc)
        products.append(record)
        usd_val = record["priceUsd"]["units"] + \
            record["priceUsd"]["nanos"] / 1_000_000_000
        _log(
            f"Added local product id={record['id']} name='{record['name']}' sub_cat='{sub_cat}' price_usd={usd_val:.2f}")
        category_counts[sub_cat] = category_counts.get(sub_cat, 0) + 1
        if len(products) >= local_limit:
            break

    payload = {"products": products}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _log(
        f"Wrote {len(products)} products to {out_path} and images to {local_img_dir}")


def run_gcp(args: argparse.Namespace) -> None:
    _log("Starting GCP mode: GCS upload, AlloyDB upserts, embeddings")
    for k in ("project", "db_host", "db_password"):
        if not getattr(args, k):
            raise SystemExit(
                f"--{k.replace('_','-')} is required for --mode gcp")

    # Init clients
    init_vertex(args.project, args.region)
    # Lazily import to avoid dependency for local mode
    from vertexai.vision_models import MultiModalEmbeddingModel, Image  # type: ignore
    mme = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")

    conn = connect_db(args)

    target = args.sample_size
    processed = 0
    seen_in_run: set[str] = set()
    category_counts: Dict[str, int] = {}
    # Compute cap thresholds
    base_cap = args.max_per_category if args.max_per_category is not None else max(
        5, target // 20)
    relax_start = int(target * max(0.0, min(1.0, args.cap_relax_start)))
    relax_final = int(target * max(0.0, min(1.0, args.cap_relax_final)))
    overflow_cap = int(math.ceil(base_cap * max(1.0, args.cap_relax_factor)))

    for obj in stream_flipkart_items(args.input, limit=None, seed=args.seed):
        if processed >= target:
            break
        pid = obj.get("pid") or obj.get("_id")
        if not pid or pid in seen_in_run:
            continue
        seen_in_run.add(pid)

        # Skip if already present in DB
        if product_exists(conn, pid):
            _log(f"Skip gcp: already in DB id={pid}")
            continue

        title = normalize_string(obj.get("title"))
        desc = normalize_string(obj.get("description"))
        price_tuple = parse_price_inr_to_usd(normalize_string(obj.get(
            "selling_price")) or normalize_string(obj.get("actual_price")), args.fx_rate)
        primary_img = choose_primary_image(obj.get("images"))
        if not title or not price_tuple or not primary_img:
            reasons = []
            if not title:
                reasons.append("missing title")
            if not price_tuple:
                reasons.append("missing/invalid price")
            if not primary_img:
                reasons.append("no image")
            _log(f"Skip gcp: reasons={'; '.join(reasons)}")
            continue

        cats = derive_categories(normalize_string(
            obj.get("category")), normalize_string(obj.get("sub_category")))
        sub_cat = cats[1] if len(cats) > 1 else (
            cats[0] if cats else "uncategorized")

        # Staged cap enforcement
        current = category_counts.get(sub_cat, 0)
        if processed < relax_start and current >= base_cap:
            _log(
                f"Skip gcp: category cap (strict) sub_cat='{sub_cat}' base_cap={base_cap}")
            continue
        if processed < relax_final and current >= overflow_cap:
            _log(
                f"Skip gcp: category cap (relaxed) sub_cat='{sub_cat}' overflow_cap={overflow_cap}")
            continue

        slug = slugify_name(title or str(pid))
        object_name = f"products/{slug}.jpg"
        _log(
            f"Uploading image to GCS object={object_name} for id={pid} name='{title}'")
        https_url = ensure_gcs_object(args.bucket, object_name, primary_img)
        _log(f"Uploaded image: {https_url}")
        combined_desc = f"{title}. {desc}" if desc else title
        record = build_product_record(
            obj,
            picture_url=https_url,
            price_usd=price_tuple,
            categories=cats,
            description_text=combined_desc,
        )
        # add DB-only fields
        record["product_image_url"] = https_url
        record["metadata"] = {
            "brand": normalize_string(obj.get("brand")),
            "average_rating": normalize_string(obj.get("average_rating")),
            "discount": normalize_string(obj.get("discount")),
            "out_of_stock": obj.get("out_of_stock"),
            "url": normalize_string(obj.get("url")),
            "product_details": obj.get("product_details"),
            "original_images": obj.get("images"),
        }

        # --- Compute text+image embeddings in a single call (1408-d) ---
        try:
            image_uri = https_to_gcs_uri(https_url)
            img = Image.load_from_file(image_uri)
            emb = mme.get_embeddings(
                image=img, contextual_text=combined_desc, dimension=1408)
            text_vec = list(emb.text_embedding) if hasattr(
                emb, "text_embedding") else None
            image_vec = list(emb.image_embedding) if hasattr(
                emb, "image_embedding") else None
        except Exception as exc:
            _log(f"WARN: embedding failed for id={record['id']}: {exc}")
            text_vec = None
            image_vec = None

        # Prepare vector literals for pgvector
        record["text_vec"] = format_vector_for_pg(
            text_vec) if text_vec else None
        record["image_vec"] = format_vector_for_pg(
            image_vec) if image_vec else None
        record["text_model"] = "multimodalembedding@001" if text_vec else None
        record["image_model"] = "multimodalembedding@001" if image_vec else None

        upsert_product(conn, record)
        _log(
            f"Upserted product id={record['id']} name='{record['name']}' sub_cat='{sub_cat}'")
        processed += 1
        category_counts[sub_cat] = category_counts.get(sub_cat, 0) + 1

    _log(f"Upserted {processed} products.")
    if processed < target:
        _log(
            f"WARN: reached end of input before loading {target} items; loaded {processed}.")

    # Removed in-DB text embedding step; we now use Vertex AI multimodal text embeddings (1408-d)
    # run_text_embeddings_in_db(conn)

    # Removed image embedding backfill; embeddings computed per record above
    # while True:
    #     batch = fetch_products_missing_image_embeddings(conn, batch_size=100)
    #     if not batch:
    #         break
    #     for pid, https_url in batch:
    #         try:
    #             img = Image.load_from_uri(https_url)
    #             emb = mme.get_embeddings(image=img, dimension=1408)
    #             vec = list(emb.image_embedding)
    #             update_image_embedding(conn, pid, vec)
    #             _log(f"Embedded image vector for id={pid}")
    #         except Exception as exc:
    #             _log(f"WARN: image embedding failed for id={pid}: {exc}")

    _log("GCP import complete.")


def main() -> None:
    args = parse_args()
    _log(f"Mode={args.mode}, sample_size={args.sample_size}, region={args.region}")
    if args.mode == "local":
        run_local(args)
    else:
        run_gcp(args)


if __name__ == "__main__":
    main()
