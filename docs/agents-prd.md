# Online Boutique Agentic Workflows – Product Requirements Document (PRD)

Version: 1.0
Owner: AI Product Manager
Status: Draft

## 0. Executive Summary
We will introduce an agentic layer, built with Google Agent Development Kit (ADK), as a new Python microservice (“agents-gateway”) that augments the existing Online Boutique with: semantic product search, image similarity search, personalized shopping assistance, and post‑purchase support. The new service exposes a simple HTTP API for the frontend, leaving existing backend microservices unchanged. Agents use Vertex AI Gemini models and Vertex AI Multimodal Embeddings for reasoning and vector retrieval; pgvector on AlloyDB provides vector search over catalog data.

References (used to inform this PRD):
- ADK home and docs: [https://google.github.io/adk-docs/](https://google.github.io/adk-docs/)
- ADK Quickstart (env, runtime): [Quickstart](https://google.github.io/adk-docs/get-started/quickstart/#env)
- Agent Team tutorial (router + specialists): [Agent Team](https://google.github.io/adk-docs/tutorials/agent-team/)
- Agents (LLM, Workflow): [Agents](https://google.github.io/adk-docs/agents/llm-agents/), [Workflow agents](https://google.github.io/adk-docs/agents/workflow-agents/)
- Tools (Function Tools, context, auth): [Tools](https://google.github.io/adk-docs/tools/)
- Sessions & Memory: [Sessions/Memory](https://google.github.io/adk-docs/sessions/)
- Deploy (Agent Engine / Cloud Run / GKE): [Deploy](https://google.github.io/adk-docs/deploy/)

## 1. Goals & Non‑Goals
### 1.1 Goals
- Add intelligent search and assistance with minimal changes to existing services.
- Provide an HTTP agent API the frontend can call.
- Keep all backend integrations read‑only by default; agents return structured “intents” for the frontend to execute.
- Support personalization using Session State and optional long‑term Memory.
- Ground decisions in store data (AlloyDB + pgvector) and official policies.

### 1.2 Non‑Goals
- Replacing existing microservices or changing their protocols.
- Direct writes to transactional systems from agents (initial rollout).
- Building a new identity stack (use existing auth; adopt ADK tool auth for future PII flows).

## 2. Use Cases & User Stories
1) As a shopper, I want natural‑language search (“vintage sunglasses under $150”), so I get relevant products.
2) As a shopper, I want to upload or select an image to find visually similar items.
3) As a shopper, I want a personal shopper that suggests items considering my preferences, budget, and recent activity.
4) As a customer, I want instant support for returns and policies grounded in our docs.
5) As a merchandiser, I want internal endpoints to generate reports or copy (phase 2+ optional).

## 3. Architecture Overview
- New service: `agents-gateway` (Python, ADK, FastAPI) running an agent team.
- Frontend calls agents‑gateway via HTTP (feature‑flagged UI entry points).
- Data sources: AlloyDB (read‑only pgvector), GCS (images), Vertex AI (LLM + embeddings).
- Authentication: GKE Workload Identity for runtime; Application Default Credentials for Vertex AI.

## 4. Agent Team Design
### 4.1 Boutique Host Agent (Router, LlmAgent)
- Purpose: Classify intent, coordinate sub‑agents.
- Model: Gemini (e.g., `gemini-2.0-flash`).
- Inputs: user text, optional userContext.
- Tools used: AgentTools wrapping specialists.

### 4.2 Product Discovery Agent (LlmAgent)
- Purpose: Semantic text search over `catalog_items.product_embedding`.
- Tool: `text_vector_search(query)`: Vertex text embedding (multimodalembedding@001, 1408) → pgvector KNN.
- Output: Top‑N product IDs + fields + rationale.

### 4.3 Image Search Agent (LlmAgent)
- Purpose: Similarity search over `catalog_items.product_image_embedding`.
- Tool: `image_vector_search(gcs_or_https)`: normalize to gs:// → Vertex image embed 1408 → pgvector KNN.
- Output: Top‑N products + fields + rationale.

### 4.4 Recommendation Agent (LlmAgent)
- Purpose: Blend user context with discovery results; apply constraints (price/brand/category diversity).
- Tools: `get_user_context()` (from Session State/Memory), `text_vector_search()`.
- Output: Re‑ranked items + “why this” reasons.

### 4.5 Checkout Assistant Agent (LlmAgent)
- Purpose: Create advisory cart plans (no mutations).
- Tool: `draft_cart_plan(products[])` → structured intent for frontend to perform.

### 4.6 Customer Support Router (LlmAgent) → Returns Workflow (SequentialAgent)
- Deterministic sub‑agents:
  - VerifyPurchaseAgent (tool `get_order_details`) – read‑only
  - CheckReturnEligibilityAgent (tool `check_policy`) – rules/KB grounded
  - GenerateRMAAgent (tool `draft_return_intent`) – structured output only
- FAQ path: `search_policy_kb(question)` (RAG over internal docs).

(ADK guidance: LlmAgent for routing; SequentialAgent for deterministic flows; see [Agents](https://google.github.io/adk-docs/agents/llm-agents/), [Workflow agents](https://google.github.io/adk-docs/agents/workflow-agents/))

## 5. Tools Specification (FunctionTools)
All tools follow ADK FunctionTool guidance with type hints and rich docstrings ([Function tools](https://google.github.io/adk-docs/tools/function-tools/)).

### 5.1 text_vector_search(query: str, top_k: int = 10) -> List[dict]
- Pre‑conditions: Vertex AI initialized; AlloyDB reachable; table `catalog_items` has `product_embedding VECTOR(1408)`.
- Steps:
  1. Compute text embedding (multimodalembedding@001, dimension=1408).
  2. Format vector for pgvector `[v1,...]` and run: `ORDER BY product_embedding <-> qvec LIMIT top_k`.
  3. Return `{id, name, description, picture, product_image_url, distance}`.
- Errors: Empty embedding; DB unreachable → surface tool error in agent.

### 5.2 image_vector_search(gcs_or_https: str, top_k: int = 10) -> List[dict]
- Pre‑conditions: normalize https to `gs://`; compute image embedding 1408.
- Query: `ORDER BY product_image_embedding <-> qvec LIMIT top_k`.
- Output: same shape as text search.

### 5.3 get_user_context(user_key: str) -> dict
- Reads session State and/or Memory (VertexAiMemoryBankService) to fetch preferences.
- Returns filters (price band, brands, categories) and recent intents.

### 5.4 draft_cart_plan(products: List[str]) -> dict
- Returns an advisory structure: `{add: [{id, qty}], notes: [...]}`.

### 5.5 get_order_details(order_id: str, email: str) -> dict (Phase 2)
- Read‑only OMS proxy or stub; requires auth when implemented (see ADK tool auth: [Authentication](https://google.github.io/adk-docs/tools/authentication/)).

### 5.6 check_policy(question: str) -> dict
- Grounded Q&A via local policy docs or Vertex AI Search; returns decision bits.

### 5.7 draft_return_intent(order_id: str, items: List[str], reason: str) -> dict
- Returns `{intent: 'return', order_id, items, reason}` for frontend execution.

## 6. API (agents-gateway)
- POST `/agent/query`: body `{text, userContext?}` → `[{product, distance, why}]`.
- POST `/agent/image`: body `{gcsUrl, userContext?}` → same shape.
- POST `/agent/support`: body `{text, userContext?}` → `{answer, citations?, return_intent?}`.
- POST `/agent/recommend`: body `{userContext?}` → `[{product, score, why}]`.
- All endpoints return JSON; latency target P50 ≤ 1.5s (KNN+embed).

## 7. Data & Schema
- Table `catalog_items` must include:
  - `product_embedding VECTOR(1408)`, `product_image_embedding VECTOR(1408)`
  - ANN indexes (ivfflat) with tuned lists (start 100; tune later).
- No schema changes to other services.

## 8. Security & Privacy
- Read‑only DB access for agent tools.
- No PII in prompts; pass non‑PII user_key.
- For future authenticated tools (orders), follow ADK tool credential handoff (request_credential flow).
- Content moderation callback before model; retry + circuit breakers for tools ([Callbacks](https://google.github.io/adk-docs/callbacks/design-patterns-and-best-practices/)).

## 9. Deployment
- Containerize `agents-gateway` (FastAPI + ADK).
- GKE Deployment with ServiceAccount annotated to GSA; optional alloydb-auth-proxy sidecar.
- Config via env/Secret Manager. CI/CD with Skaffold or Cloud Build.
- Option B: Deploy to Vertex AI Agent Engine after MVP ([Deploy](https://google.github.io/adk-docs/deploy/agent-engine/)).

## 10. Acceptance Criteria
- Search endpoints return relevant products for representative queries (top‑10) with latency targets.
- Image search works for gs:// and storage HTTPS URLs.
- Recommendation returns re‑ranked results influenced by provided userContext.
- Support endpoint answers FAQs and returns structured return_intent when appropriate.
- No direct backend mutations; frontend executes plans.

## 11. Analytics & Observability
- Log tool calls and timings; emit traces (ADK tracing) to Cloud Trace.
- Basic metrics: request rate, latency, tool error rate, embedding usage.

## 12. Risks & Mitigations
- Model drift/quality → keep prompts/versioning; add offline evals.
- Latency spikes → cache popular embeddings; add pgvector indexes; size top_k.
- Data mismatch → validate schema at startup; health checks.

## 13. Phased Roadmap & Tasks

### Phase 1 – Agents-gateway MVP (Search + Image Search)
- Infra
  - Create repo module `agents-gateway` (Python) with FastAPI + ADK.
  - Add Kustomize component and ServiceAccount with WI.
  - Optional alloydb-auth-proxy sidecar.
- Tools
  - Implement `text_vector_search`, `image_vector_search` (FunctionTools; robust docstrings; input validation).
- Agents
  - Boutique Host Agent (router) with AgentTools calling Discovery + Image agents.
  - Product Discovery Agent; Image Search Agent.
- API
  - `/agent/query`, `/agent/image` endpoints.
- Frontend
  - Feature‑flagged calls to agents‑gateway for search boxes and image search.
- Tests
  - Unit tests for tools (mock DB/Vertex); integration test against staging DB.

### Phase 2 – Recommendation Agent + Personalization
- Tools
  - `get_user_context` (Session State; optionally Memory for profile).
- Agent
  - Recommendation Agent that re‑ranks discovery results using constraints (price/brand/category diversity). Return “why this”.
- API
  - `/agent/recommend` endpoint.
- Frontend
  - Shopper CTA; display reasons.

### Phase 3 – Support Router + FAQ & Returns Workflow (deterministic)
- Tools
  - `search_policy_kb` (local docs / RAG).
  - Stubs for `get_order_details`, `check_policy`, `draft_return_intent`.
- Agents
  - Support Router (LlmAgent) and Returns Workflow (SequentialAgent) with static rules first.
- API
  - `/agent/support` endpoint.
- Frontend
  - Help widget consumes responses; executes `return_intent` via existing flow.

### Phase 4 – Hardening & Optional Internal Agents
- Add content/SEO and merchandising internal endpoints (Artifacts for PDF/CSV).
- Add callbacks for moderation, retries, audit logging.
- Performance tuning (embedding cache, ANN lists, connection pooling).

## 14. Detailed Task Breakdown (Engineering)
- Bootstrap service
  - requirements.txt (google-adk, fastapi, uvicorn, google-cloud-aiplatform, psycopg2-binary)
  - app layout: `agents/` (agents.py, tools.py, router.py), `api/` (server.py), `config/`, `tests/`
- ADK construction
  - Define LlmAgents with clear instruction prompts and safety constraints.
  - Build FunctionTools with type hints + rich docstrings; validate params; raise structured errors.
  - Use ToolContext.state for per‑session prefs; plan for VertexAiMemoryBankService later.
- DB layer
  - pgx queries (psycopg2) with vector literal formatting; safe SQL params.
  - Health check query at startup (confirm columns and dims=1408).
- Vertex AI
  - Single model instance per process; reuse client objects; dimension=1408.
  - Normalize image URLs to gs://.
- API + Schemas
  - Pydantic models for requests/responses; error mapping.
- Observability
  - Logging, trace spans per tool; request IDs.
- Security
  - WI + least‑privilege; redact sensitive fields in logs; rate limit.

## 15. Open Questions
- Which frontend surfaces should integrate first (global search vs. dedicated assistant pane)?
- Do we need a minimal OMS shim for `get_order_details` or is a stub sufficient for MVP?
- Should we target Vertex AI Agent Engine for stateful prod later (managed sessions)?

---
This PRD adheres to ADK guidelines (agents, tools, sessions/memory, and deployment) and the proposed minimal‑change architecture. It focuses on additive capabilities, deterministic support flows, and safe read‑only integrations while delivering meaningful agentic UX improvements for Online Boutique.
