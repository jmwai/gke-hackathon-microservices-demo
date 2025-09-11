# Catalog Importer (tools/import_products.py)

This document explains how the Flipkart → Online Boutique importer works, how to configure and run it, what it writes to AlloyDB and GCS, and how to tune its behavior.

## Overview

The importer ingests products from a large JSON file and loads them into AlloyDB. It uploads primary images to a GCS bucket, generates both text and image embeddings using Vertex AI Multimodal Embeddings, and stores vectors in pgvector columns for semantic search.

- Input: `data/flipkart_fashion_products_dataset.json` (top-level JSON array of products)
- Output:
  - GCS: `gs://<bucket>/products/<slug>.jpg`
  - AlloyDB table: `catalog_items`
  - Optional local mode: writes `src/productcatalogservice/products.json` for dev

## Requirements

- Python deps: `google-cloud-aiplatform`, `google-cloud-storage`, `requests`, `psycopg2-binary`, `ijson`
- Google Cloud:
  - Enable `aiplatform.googleapis.com` for Vertex AI
  - Auth: `gcloud auth application-default login` (or use a service account key for ADC)
  - GCS bucket (Uniform bucket-level access supported)
- AlloyDB connectivity: either local AlloyDB Auth Proxy (`127.0.0.1:5432`) or private IP with TLS

Install example:

```bash
pip install --upgrade google-cloud-aiplatform google-cloud-storage requests psycopg2-binary ijson
```

## Database Schema (AlloyDB)

The importer expects and populates the following columns in database `postgres`, table `catalog_items`:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
-- (google_ml_integration is optional; importer uses Vertex for text+image)

CREATE TABLE IF NOT EXISTS catalog_items (
  id TEXT PRIMARY KEY,
  name TEXT,
  description TEXT,
  picture TEXT,
  product_image_url TEXT,
  price_usd_currency_code TEXT,
  price_usd_units INTEGER,
  price_usd_nanos BIGINT,
  categories TEXT,
  metadata JSONB,
  product_embedding VECTOR(1408),
  embed_model TEXT,
  product_image_embedding VECTOR(1408),
  image_embed_model TEXT
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_catalog_items_categories
  ON catalog_items ((lower(categories)));

-- ANN indexes (tune lists for dataset size)
CREATE INDEX IF NOT EXISTS idx_catalog_items_product_embedding
  ON catalog_items USING ivfflat (product_embedding vector_l2_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_catalog_items_image_embedding
  ON catalog_items USING ivfflat (product_image_embedding vector_l2_ops) WITH (lists = 100);
```

Notes:
- Vector dims are 1408 for both text and image embeddings because the importer uses Vertex AI `multimodalembedding@001`.
- Currency is normalized to USD.

## How Embeddings Are Generated

The importer uses Vertex AI Multimodal Embeddings to compute both text and image vectors in a single call:

- Text: `contextual_text=<title + description>` → 1408-d vector
- Image: `gs://<bucket>/products/<slug>.jpg` → 1408-d vector
- Model: `multimodalembedding@001`
- SDK call: `MultiModalEmbeddingModel.get_embeddings(image=..., contextual_text=..., dimension=1408)`

The vectors are converted to pgvector literals (e.g., `[0.1234,0.5678,...]`) and written into `product_embedding` and `product_image_embedding`. The model columns (`embed_model`, `image_embed_model`) are set to `multimodalembedding@001` when present.

## GCS Upload Behavior

- Images are uploaded to the configured bucket under `products/<slug>.jpg`.
- With Uniform bucket-level access (UBLA) enabled, the importer does not call object ACLs. Public access should be controlled at the bucket IAM level if needed:

```bash
gcloud storage buckets add-iam-policy-binding gs://<bucket> \
  --member=allUsers --role=roles/storage.objectViewer
```

The importer returns the HTTPS URL `https://storage.googleapis.com/<bucket>/<object>`, and converts it to `gs://` internally for Vertex embeddings input.

## Modes

- `--mode local` (no GCP): writes a small `products.json` for the product service and saves sample images locally.
- `--mode gcp`: pushes to GCS + AlloyDB and computes embeddings via Vertex AI.

## CLI Arguments

Key arguments (see `--help` for full list):

- `--mode {local,gcp}`
- `--input <path>`: JSON file path
- `--sample-size <N>`: number of new products to insert (exact fill behavior)
- `--bucket <name>`: target GCS bucket
- `--project <id>`, `--region <loc>`: Vertex/AlloyDB region
- DB: `--db-host`, `--db-port` (5432), `--db-name` (postgres), `--db-user` (postgres), `--db-password`
- Category cap controls (gcp mode only):
  - `--max-per-category`: base cap; default `max(5, sample_size//20)`
  - `--cap-relax-start`: fraction of target to start relaxing (default `0.5`)
  - `--cap-relax-factor`: overflow multiplier (default `1.5`)
  - `--cap-relax-final`: fraction to ignore caps (default `0.9`)

## Ingestion Logic (GCP Mode)

For each candidate product in the JSON stream:
1. Deduplicate by run (skip if already seen in this execution).
2. Skip if already present in DB (`SELECT 1 FROM catalog_items WHERE id = $1`).
3. Validate fields (title, description, price, primary image). Skip on missing.
4. Enforce per-category caps with staged relaxation:
   - Stage A (strict): `< relax_start` → enforce `base_cap`.
   - Stage B (relaxed): `[relax_start, relax_final)` → enforce `overflow_cap = ceil(base_cap * cap_relax_factor)`.
   - Stage C (final): `≥ relax_final` → ignore caps to reach target.
5. Upload image to GCS, compute text + image embeddings in one call.
6. UPSERT row with vectors and metadata.
7. Repeat until exactly `--sample-size` new rows are inserted or input is exhausted (logs a warning if underfilled).

This guarantees idempotence (skips IDs already in DB) and exact fill under normal conditions.

## Usage Examples

- Via AlloyDB Auth Proxy (recommended during dev):

```bash
python3 tools/import_products.py \
  --mode gcp \
  --input data/flipkart_fashion_products_dataset.json \
  --sample-size 200 \
  --bucket online-boutique \
  --fx-rate 88 \
  --project gemini-adk-vertex-2025 \
  --region europe-west1 \
  --db-host 127.0.0.1 \
  --db-port 5432 \
  --db-name postgres \
  --db-user postgres \
  --db-password 'YOUR_PASSWORD'
```

- Direct to private IP (ensure TLS connectivity in your environment):

```bash
python3 tools/import_products.py \
  --mode gcp \
  --input data/flipkart_fashion_products_dataset.json \
  --sample-size 200 \
  --bucket online-boutique \
  --fx-rate 88 \
  --project gemini-adk-vertex-2025 \
  --region europe-west1 \
  --db-host 10.95.0.2 \
  --db-port 5432 \
  --db-name postgres \
  --db-user postgres \
  --db-password 'YOUR_PASSWORD'
```

## Error Handling & Troubleshooting

- Vertex AI SDK missing: install `google-cloud-aiplatform` and enable API.
- GCS UBLA error on ACLs: the importer no longer uses object ACLs; set bucket-level IAM if you require public reads.
- Embedding errors: ensure `gs://` URIs are passed to Vertex (the importer auto-converts HTTPS storage URLs).
- Undershoot sample size: the importer continues scanning until it reaches the target; if the file doesn’t have enough valid/unique products, it logs a warning.

## Security & IAM

- Vertex AI: ADC identity must have permission to call embeddings. Enable API.
- GCS: ADC identity must have write access to the target bucket; optional public reader policy for images.
- AlloyDB: provide valid credentials; with private IP, enforce TLS as required; with auth proxy, connect to `127.0.0.1`.

## Notes on Performance

- JSON streaming uses `ijson` when available to avoid loading the entire file.
- Embeddings are computed per-product to keep logic simple; batch text embedding is possible but not required.
- ANN indexes speed up later vector search queries.

## Related Tools

- `tools/vector_search_test.py`: quick text/image vector search against `catalog_items` using Vertex embeddings and pgvector KNN (`<->`).

---

For questions or issues, check logs printed by the importer (timestamps prefixed) and verify IAM/API setup for Vertex, GCS, and AlloyDB connectivity.
