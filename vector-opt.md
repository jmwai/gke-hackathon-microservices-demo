# 🚀 **Vector Search Optimization Plan**

## 📊 **Current State Analysis**

### **✅ Database Status:**
- **✅ Data Loaded**: Products are imported and accessible via `/test-db`
- **✅ Database Schema**: `catalog_items` table exists with proper columns
- **⚠️ Vector Dimensions**: DB has `VECTOR(768)` but agents use `1408D` vectors
- **❌ Vector Indexes**: No IVFFLAT/HNSW indexes detected

### **🔍 Agents Using Vector Search:**

| Agent | Vector Search Usage | Current Implementation | Impact |
|-------|-------------------|----------------------|--------|
| **`product_discovery_agent`** | Text search (`text_vector_search`) | 🚨 1408D vectors | **HIGH** - Main search |
| **`image_search_agent`** | Image search (`image_vector_search`) | 🚨 1408D vectors | **HIGH** - Visual search |
| **`shopping_assistant_agent`** | Text recommendations (`text_vector_search`) | 🚨 1408D vectors | **MEDIUM** - Recommendations |
| **`recommendation_agent` (boutique)** | Text search (`text_vector_search`) | 🚨 1408D vectors | **MEDIUM** - Recommendations |
| **`shoppingassistantservice`** | LangChain AlloyDBVectorStore | ✅ Uses `embedding-001` | **LOW** - Separate service |

### **🚨 Critical Issues:**
1. **Vector Dimension Mismatch**: DB stores 768D, agents generate 1408D
2. **Missing Vector Indexes**: No IVFFLAT indexes for fast ANN search
3. **No Embedding Cache**: Every search hits Vertex AI API
4. **Connection Pool Issues**: Custom pooling without optimization

---

## 🎯 **Optimization Strategy**

### **📐 Dimension Strategy Decision:**
**RECOMMENDATION: Standardize on 768D** 
- **Rationale**: 
  - DB already has 768D embeddings populated
  - 768D is faster (smaller vectors = faster search)
  - `textembedding-gecko@003` provides good quality at 768D
  - Avoids massive data re-import
  - `shoppingassistantservice` already uses this approach

### **🔄 Migration Approach:**
**PHASED ROLLOUT** to minimize downtime and risk:

---

## 📋 **Phase 1: Critical Infrastructure (Week 1)**

### **🚨 URGENT: Fix Vector Dimension Mismatch**

#### **Step 1.1: Update Agent Embedding Functions**
```python
# Replace _embed_text_1408 with _embed_text_768
def _embed_text_768(text: str) -> List[float]:
    if text in _embedding_cache:
        return _embedding_cache[text]
    
    _ensure_vertex()
    # Use textembedding-gecko@003 for consistency with DB
    from vertexai.language_models import TextEmbeddingModel
    model = TextEmbeddingModel.from_pretrained("textembedding-gecko@003")
    embeddings = model.get_embeddings([text])
    
    result = embeddings[0].values
    _embedding_cache[text] = result
    return result
```

#### **Step 1.2: Update Image Embeddings (If Needed)**
```python
# Check if product_image_embedding column uses 768D or 1408D
# Update _embed_image_1408_from_bytes accordingly
```

#### **Step 1.3: Create Vector Indexes IMMEDIATELY**
```sql
-- Create indexes CONCURRENTLY to avoid downtime
CREATE INDEX CONCURRENTLY idx_catalog_product_embedding_cosine 
ON catalog_items USING ivfflat (product_embedding vector_cosine_ops) 
WITH (lists = 100);

-- For image embeddings (if they exist and are used)
CREATE INDEX CONCURRENTLY idx_catalog_image_embedding_cosine 
ON catalog_items USING ivfflat (product_image_embedding vector_cosine_ops) 
WITH (lists = 100);

-- Alternative: L2 distance indexes if using <-> operator
CREATE INDEX CONCURRENTLY idx_catalog_product_embedding_l2 
ON catalog_items USING ivfflat (product_embedding vector_l2_ops) 
WITH (lists = 100);
```

**Expected Impact: 20s → 0.5-2s** ⚡

---

## 📋 **Phase 2: Performance Infrastructure (Week 2)**

### **Step 2.1: Implement Redis Embedding Cache**
```python
# New caching layer
import redis
import json
import hashlib

class EmbeddingCache:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'redis-service'),
            port=6379,
            decode_responses=True
        )
    
    def get_text_embedding(self, text: str) -> Optional[List[float]]:
        cache_key = f"embed:text:768:{hashlib.sha256(text.encode()).hexdigest()}"
        cached = self.redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
        return None
    
    def set_text_embedding(self, text: str, embedding: List[float], ttl: int = 3600):
        cache_key = f"embed:text:768:{hashlib.sha256(text.encode()).hexdigest()}"
        self.redis_client.setex(cache_key, ttl, json.dumps(embedding))
```

### **Step 2.2: Optimize Database Connection Pool**
```python
def init_optimized_alloydb_pool():
    from psycopg2.pool import ThreadedConnectionPool
    
    return ThreadedConnectionPool(
        minconn=5,
        maxconn=20,
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        # Connection optimization
        keepalives_idle=600,
        keepalives_interval=30,
        keepalives_count=3,
        # Performance tuning
        application_name="agents-gateway",
        connect_timeout=10
    )
```

### **Step 2.3: Optimize Vector Search Queries**
```python
def optimized_text_vector_search(query: str, filters: Optional[Dict], top_k: int):
    # Use cached embedding
    embedding_cache = EmbeddingCache()
    vec = embedding_cache.get_text_embedding(query)
    if not vec:
        vec = _embed_text_768(query)
        embedding_cache.set_text_embedding(query, vec)
    
    # Optimized query - minimal columns, proper indexing
    sql = """
    SELECT id, name, picture, product_image_url,
           (product_embedding <=> %s) AS distance
    FROM catalog_items 
    WHERE product_embedding IS NOT NULL
    ORDER BY product_embedding <=> %s 
    LIMIT %s
    """
    
    params = [vector_literal(vec), vector_literal(vec), top_k]
    # Add filters if needed...
```

**Expected Impact: 0.5-2s → 0.1-0.3s** ⚡

---

## 📋 **Phase 3: Advanced Optimizations (Week 3)**

### **Step 3.1: Implement Hybrid Search**
```python
def hybrid_search(query: str, filters: Optional[Dict], top_k: int):
    # Step 1: Pre-filter with category if provided
    base_sql = "FROM catalog_items WHERE product_embedding IS NOT NULL"
    if filters and filters.get("category"):
        base_sql += " AND categories ILIKE %s"
    
    # Step 2: Vector search on filtered subset
    # Step 3: Optional: Combine with text search for rare cases
```

### **Step 3.2: Add Performance Monitoring**
```python
import time
from contextlib import contextmanager

@contextmanager
def measure_search_time(search_type: str):
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        _log(f"PERF: {search_type} took {duration:.3f}s")
        # Send to monitoring system
```

### **Step 3.3: Deploy Redis for Caching**
```yaml
# kubernetes-manifests/redis.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
spec:
  template:
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
```

**Expected Impact: 0.1-0.3s → 0.05-0.1s** ⚡

---

## 📋 **Phase 4: Testing & Validation (Week 4)**

### **🧪 Testing Strategy:**

#### **Step 4.1: Individual Agent Testing**
```bash
# Test each agent independently
curl -X POST http://localhost:8080/apps/product_discovery_agent/users/test/sessions
curl -X POST http://localhost:8080/run -d '{"query": "comfortable shoes for walking"}'

# Measure response times
time curl -X POST http://localhost:8080/run -d '{"query": "elegant dress"}'
```

#### **Step 4.2: Load Testing**
```python
# Performance test script
import asyncio
import aiohttp
import time

async def test_concurrent_searches():
    queries = [
        "comfortable shoes",
        "elegant dress", 
        "winter jacket",
        "running shoes",
        "casual wear"
    ]
    
    # Test 10 concurrent requests
    start = time.time()
    async with aiohttp.ClientSession() as session:
        tasks = [search_agent(session, q) for q in queries * 2]
        results = await asyncio.gather(*tasks)
    end = time.time()
    
    print(f"10 concurrent searches: {end-start:.2f}s")
    print(f"Average per search: {(end-start)/10:.2f}s")
```

#### **Step 4.3: Agent Integration Testing**
| Agent | Test Query | Expected Results | Performance Target |
|-------|------------|------------------|-------------------|
| `product_discovery_agent` | "comfortable shoes for walking" | 5+ shoe products | < 0.2s |
| `image_search_agent` | Upload shoe image | Similar shoes | < 0.3s |
| `shopping_assistant_agent` | "clothes for skiing trip" | Appropriate clothing | < 0.2s |
| `recommendation_agent` | User context + "casual wear" | Personalized results | < 0.2s |

#### **Step 4.4: Frontend Integration Testing**
```javascript
// Test search from frontend
async function testSearchPerformance() {
    const start = performance.now();
    const response = await fetch('/api/agent-search', {
        method: 'POST',
        body: JSON.stringify({query: 'comfortable shoes'})
    });
    const end = performance.now();
    console.log(`Frontend search took: ${end-start}ms`);
}
```

---

## 📊 **Expected Performance Improvements**

| Phase | Current State | After Optimization | Improvement |
|-------|---------------|-------------------|-------------|
| **Phase 1** | 20+ seconds | 0.5-2 seconds | **10-40x faster** |
| **Phase 2** | 0.5-2 seconds | 0.1-0.3 seconds | **5-20x faster** |
| **Phase 3** | 0.1-0.3 seconds | 0.05-0.1 seconds | **2-6x faster** |
| **Total** | **20+ seconds** | **0.05-0.1 seconds** | **200-400x faster** |

### **🎯 Success Metrics:**
- **Search Response Time**: < 200ms per search
- **Agent Response Time**: < 500ms total (including LLM processing)
- **Frontend UX**: < 1s from query to results display
- **Concurrent Capacity**: Handle 50+ concurrent searches
- **Cache Hit Rate**: > 80% for repeated queries

---

## 🚨 **Risk Mitigation**

### **⚠️ Risks & Mitigations:**
1. **Index Creation Downtime**: Use `CONCURRENTLY` keyword
2. **Cache Miss Performance**: Maintain fallback to direct embedding generation
3. **Redis Failure**: Graceful degradation without cache
4. **Vector Dimension Issues**: Thorough testing before production deploy

### **🔄 Rollback Plan:**
```bash
# If issues arise, rollback steps:
1. Revert agent code to 1408D (git revert)
2. Drop problematic indexes if needed
3. Disable Redis cache layer
4. Fall back to original implementation
```

---

## ⏱️ **Implementation Timeline**

| Week | Focus | Deliverables | Risk Level |
|------|--------|-------------|------------|
| **Week 1** | 🚨 Critical Fixes | Fix dimensions + Create indexes | **HIGH** |
| **Week 2** | ⚡ Performance | Caching + Connection optimization | **MEDIUM** |
| **Week 3** | 🚀 Advanced | Hybrid search + Monitoring | **LOW** |
| **Week 4** | 🧪 Testing | Full validation + Load testing | **LOW** |

### **🎯 Immediate Next Steps:**
1. **TODAY**: Fix vector dimension mismatch in agents
2. **TODAY**: Create vector indexes on database  
3. **TOMORROW**: Test basic functionality with all agents
4. **THIS WEEK**: Deploy caching infrastructure

This plan should reduce your vector search time from **20 seconds to under 200ms** - a **100x improvement**! 🚀

## 🎯 **Summary**

I've created a comprehensive **4-phase optimization plan** that will transform your vector search performance from **20 seconds to under 200ms** - a **100x improvement**!

### **🔍 Key Findings:**
- **4 agents** use vector search with **dimension mismatch** (1408D vs 768D in DB)
- **No vector indexes** causing full table scans
- **No embedding caching** causing repeated API calls
- Database already loaded with 768D embeddings

### **🚀 Strategic Approach:**
1. **Phase 1 (Week 1)**: Fix critical issues (dimensions + indexes) → **10-40x faster**
2. **Phase 2 (Week 2)**: Add caching + optimize connections → **5-20x faster** 
3. **Phase 3 (Week 3)**: Advanced optimizations + monitoring → **2-6x faster**
4. **Phase 4 (Week 4)**: Comprehensive testing across all agents

### **🎯 Immediate Action Items:**
1. **Fix vector dimensions** in all 4 agent implementations
2. **Create IVFFLAT indexes** on the database
3. **Test each agent** with the new implementation
4. **Deploy Redis** for embedding caching

The plan ensures **minimal risk** with phased rollouts, comprehensive testing, and clear rollback procedures. All agents will benefit from the optimizations, and the testing strategy covers individual agent performance, load testing, and frontend integration.

Ready to start with Phase 1? 🚀
