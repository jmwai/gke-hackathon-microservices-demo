# agents-gateway

FastAPI + ADK service exposing agents per PRD.

Run locally:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r src/agents-gateway/requirements.txt
uvicorn src.agents-gateway.app.server:app --reload --port 8080
```

Endpoints (stubs):
- POST /agent/query
- POST /agent/image (multipart upload)
- POST /agent/support
- POST /agent/recommend


