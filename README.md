# 🧠 LLM Semantic Cache

A production-grade semantic caching layer for LLM APIs that reduces response latency by **94%** and cuts API costs by **40%** using two-stage vector retrieval and cross-encoder reranking.

## 🎯 Project Highlights

Every LLM API call costs money and takes ~1 second. When users ask semantically similar questions, why pay twice? This system intercepts requests, finds semantically equivalent cached responses, and serves them in **58ms** instead of **1020ms**.

- **Two-stage retrieval** — fast FAISS bi-encoder search + precise cross-encoder reranking (industry-standard RAG pattern)
- **Adaptive thresholds** — different similarity cutoffs per query type (factual vs explanatory)
- **Persistent cache** — FAISS index + Redis survive Docker restarts via named volumes
- **60% cache hit rate** on real-world query benchmarks

## 🏗️ Architecture

```
User Request
      ↓
Query Normalization (lowercase, punctuation removal, abbreviation expansion)
      ↓
Bi-encoder Embedding (multi-qa-mpnet-base-dot-v1)
      ↓
FAISS Vector Search → top-5 candidates
      ↓
Adaptive Threshold Filter (0.76 factual / 0.82 definition / 0.90 exact)
      ↓
Cross-encoder Reranking (ms-marco-MiniLM-L-6-v2)
      ↓
Cache Hit?  → Redis → return (58ms avg)
Cache Miss? → Groq LLM → store → return (1020ms avg)
```

## 🔧 Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API | FastAPI + AsyncGroq | Non-blocking REST endpoints |
| Bi-encoder | multi-qa-mpnet-base-dot-v1 | Fast semantic similarity (768-dim) |
| Cross-encoder | ms-marco-MiniLM-L-6-v2 | Precise reranking of top candidates |
| Vector index | FAISS IndexFlatIP | Cosine similarity search |
| Cache store | Redis 7 (AOF) | Persistent response storage with TTL |
| LLM backend | Groq (llama-3.1-8b-instant) | Fast inference fallback |
| Deploy | Docker Compose + named volumes | Persistent cache across restarts |

## 📊 Benchmark Results

```
Phase 1: Populate cache with 10 seed queries
Phase 2: Test 20 semantically similar queries

Cache Hit Rate:       60.0%
Avg Cached Latency:   58ms
Avg LLM Latency:      1020ms
Latency Reduction:    94.3%
Est. Cost Savings:    40%
```

## 🎓 Key Implementation Details

### 1️⃣ Two-Stage Retrieval
```
Stage 1 — Bi-encoder (fast):
  query → embedding → FAISS → top-5 candidates in ~5ms

Stage 2 — Cross-encoder (precise):
  (query, candidate) pairs → reranker → best match score
  Only runs on 5 candidates, not entire index
```

### 2️⃣ Adaptive Similarity Threshold
```python
def get_adaptive_threshold(prompt: str) -> float:
    if any(p in prompt for p in ["capital", "who invented", "speed of"]):
        return 0.90  # factual — high precision required
    if any(p in prompt for p in ["what is", "define"]):
        return 0.82  # definition — medium threshold
    if any(p in prompt for p in ["explain", "how does"]):
        return 0.76  # explanatory — paraphrases acceptable
    return 0.82
```

### 3️⃣ Cache Hit Example
```
Query 1: "What is machine learning?"     → LLM call (1006ms)
Query 2: "Explain machine learning"      → Cache HIT (68ms) ✅
Query 3: "Can you explain what ML is?"   → Cache HIT (57ms) ✅
Query 4: "Tell me about artificial intelligence" → Cache HIT (58ms) ✅
```

### 4️⃣ Persistent Cache
```yaml
volumes:
  faiss_data:   # FAISS index survives restarts
  redis_data:   # Redis AOF persistence
```

## 🚀 Quick Start

```bash
git clone https://github.com/kaipbergen/semantic-cache
cd semantic-cache
cp .env.example .env
# Add GROQ_API_KEY to .env
docker-compose up --build
```

Open `http://localhost:8000/docs` for Swagger UI.

## 📋 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/query` | Semantic cache lookup + LLM fallback |
| `GET` | `/stats` | Hit rate, latency breakdown, cost savings |
| `GET` | `/health` | Health check |
| `DELETE` | `/cache` | Clear all cache |
| `DELETE` | `/cache/{key}` | Delete specific entry |

## 📈 Run Benchmarks

```bash
python3 -m venv venv && source venv/bin/activate
pip install httpx
python3 tests/benchmark.py
```

## 🔗 Related Projects

The Redis backend used in this project is implemented from scratch in [LiteKV](https://github.com/kaipbergen/litekv) — a C++17 distributed key-value store with epoll, AOF persistence, and master-replica replication.
