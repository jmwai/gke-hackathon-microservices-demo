## Load Flipkart Products into Online Boutique (AlloyDB + GCS + Embeddings)

### Confirmed parameters
- **Region**: europe-west1
- **FX rate**: fixed 88 INR→USD
- **Item count**: 1,000 (we will scale later)
- **Images**: public GCS bucket `boutique-demo`
- **DB**: AlloyDB (`products` database, `catalog_items` table)
- **Embeddings**: text (`textembedding-gecko@003`) + image (`multimodalembedding@001`); no `title_embedding`
- **Goal**: Enrich data for demo; keep `products.json` semantics

### Workflows

#### Local (no GCP deps)
- Stream the Flipkart JSON, map 1,000 products, and write `src/productcatalogservice/products.json` only.
- Recommended to use GCS HTTPS URLs in `picture` for consistency (but the local frontend also supports local `static` paths if desired).

Run (example):

```bash
python tools/import_products.py \
  --mode local \
  --input data/flipkart_fashion_products_dataset.json \
  --sample-size 1000 \
  --bucket boutique-demo \
  --fx-rate 88
```

Then restart `productcatalogservice` locally so it reloads `products.json`.

#### GCP (images to GCS, products to AlloyDB, embeddings)
- Upload product images to GCS `gs://boutique-demo`.
- Upsert mapped products into AlloyDB.
- Create text embeddings in-DB via `google_ml_integration` function.
- Create image embeddings via Vertex `multimodalembedding@001` and store in AlloyDB.

Run (example):

```bash
python tools/import_products.py \
  --mode gcp \
  --input data/flipkart_fashion_products_dataset.json \
  --sample-size 1000 \
  --bucket boutique-demo \
  --fx-rate 88 \
  --project <PROJECT_ID> \
  --region europe-west1 \
  --db-host <ALLOYDB_HOST_OR_IP> \
  --db-port 5432 \
  --db-name products \
  --db-user postgres \
  --db-password <PASSWORD>
```

### One-time GCP setup (manual per project)
- Enable APIs: Vertex AI, Secret Manager, AlloyDB, Cloud Storage.
- Create public bucket `gs://boutique-demo` (uniform bucket-level access) in an EU location (close to europe-west1).
- Provision AlloyDB primary instance and create `products` database.

SQL (extensions, table, indexes):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS google_ml_integration CASCADE;
GRANT EXECUTE ON FUNCTION embedding TO postgres;

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
  product_embedding VECTOR(768),
  product_image_embedding VECTOR(1408),
  embed_model TEXT,
  image_embed_model TEXT,
  metadata JSONB
);

CREATE INDEX IF NOT EXISTS catalog_items_text_vec_idx
  ON catalog_items USING ivfflat (product_embedding vector_cosine_ops) WITH (lists=100);

CREATE INDEX IF NOT EXISTS catalog_items_img_vec_idx
  ON catalog_items USING ivfflat (product_image_embedding vector_cosine_ops) WITH (lists=100);
```

### Data mapping (Flipkart → Online Boutique product)
- **id**: `pid` (fallback `_id`), must be unique string.
- **name**: `title` (trim/sanitize).
- **description**: `description` (trim/sanitize; consider max length).
- **picture**: public GCS URL `https://storage.googleapis.com/boutique-demo/products/<id>.jpg`.
- **priceUsd**: from `selling_price` (fallback `actual_price`).
  - Parse (remove commas), convert: `usd = inr / 88`.
  - Split to units/nanos: `units = floor(usd)`, `nanos = round((usd - units) * 1e9)`.
- **categories**: array derived from `[category, sub_category]`, lowercased, unique; stored in DB as comma-separated string.
- **metadata (JSONB)**: include `brand`, `average_rating`, `discount`, `out_of_stock`, `url`, `product_details`, `original_images`.

### Python tool behavior
- Modes: `local` and `gcp`.
- Input: `data/flipkart_fashion_products_dataset.json` (streamed; no full in-memory load).
- Selection: process first 1,000 valid items (or implement reservoir sampling for diversity).
- Validation: skip if missing id/title/price/image; log and continue.
- Concurrency: bounded workers (e.g., 16) for image download/upload and DB upserts.
- Idempotency: upserts with `ON CONFLICT (id) DO UPDATE`.

Upsert SQL (GCP mode):

```sql
INSERT INTO catalog_items
(id, name, description, picture, product_image_url,
 price_usd_currency_code, price_usd_units, price_usd_nanos,
 categories, metadata)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
ON CONFLICT (id) DO UPDATE SET
  name=EXCLUDED.name,
  description=EXCLUDED.description,
  picture=EXCLUDED.picture,
  product_image_url=EXCLUDED.product_image_url,
  price_usd_currency_code=EXCLUDED.price_usd_currency_code,
  price_usd_units=EXCLUDED.price_usd_units,
  price_usd_nanos=EXCLUDED.price_usd_nanos,
  categories=EXCLUDED.categories,
  metadata=EXCLUDED.metadata;
```

### Embeddings backfill

Text (in-DB using `google_ml_integration`):

```sql
UPDATE catalog_items
SET product_embedding = embedding('textembedding-gecko@003', CONCAT_WS(' ', name, description)),
    embed_model = 'textembedding-gecko@003'
WHERE product_embedding IS NULL;
```

Image (Python + Vertex `multimodalembedding@001`, europe-west1):
- For rows where `product_image_embedding IS NULL` and `product_image_url IS NOT NULL`:
  - Call Vertex multimodal embedding on the HTTPS image URL.
  - Update row: `product_image_embedding=$1, image_embed_model='multimodalembedding@001' WHERE id=$2`.
- Batch requests, reuse client, respect QPS, retry on transient errors.

Maintenance after backfill:
- Optionally `REINDEX` IVFFLAT indexes (for large updates).
- `ANALYZE catalog_items;` to refresh stats.

### Validation
- Spot check a few rows for fields and URLs.
- Embedding coverage:

```sql
SELECT COUNT(*) FROM catalog_items WHERE product_embedding IS NOT NULL;
SELECT COUNT(*) FROM catalog_items WHERE product_image_embedding IS NOT NULL;
```

- Sample vector queries:

```sql
-- text-only
SELECT id, name, (product_embedding <=> $1) AS score
FROM catalog_items
ORDER BY score ASC
LIMIT 10;

-- image-only
SELECT id, name, (product_image_embedding <=> $1) AS score
FROM catalog_items
WHERE product_image_embedding IS NOT NULL
ORDER BY score ASC
LIMIT 10;

-- hybrid (default 0.6 text / 0.4 image)
SELECT id, name,
       (0.6*(product_embedding <=> $1) + 0.4*(product_image_embedding <=> $2)) AS score
FROM catalog_items
WHERE product_image_embedding IS NOT NULL
ORDER BY score ASC
LIMIT 10;
```

### Notes and considerations
- **FX**: FX is fixed at 88 INR→USD for the run; record it in logs for traceability.
- **Images**: Use first image in `images[]`; store original URL in metadata.
- **Limits**: 1,000 products now; scale later by increasing `--sample-size` and monitoring costs/latency.
- **Costs**: Vertex calls incur cost; batch and cache when possible.
- **Errors**: Skip problematic records; log counts; make ingestion idempotent.


