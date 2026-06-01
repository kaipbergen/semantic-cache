# Semantic Cache

A production-grade semantic caching layer for LLM APIs that reduces latency by 94% and cuts API costs by 40% using vector similarity search and cross-encoder reranking.

## Architecture

```
User Request
     ↓
Query Normalization + Abbreviation Expansion
     ↓
Bi-encoder Embedding (multi-qa-mpnet-base-dot-v1)
     ↓
FAISS Vector Search (top-5 candidates)
     ↓
Adaptive Threshold Filter (0.76 – 0.90 by query type)
     ↓
Cross-encoder Reranking (ms-marco-MiniLM-L-6-v2)
     ↓
Cache Hit → Redis → 58ms avg
Cache Miss → Groq LLM → Store → 1020ms avg
```

## Benchmark Results

| Metric | Value |
|--------|-------|
| Cache Hit Rate | 60% |
| Avg Cached Latency | 58ms |
| Avg LLM Latency | 1020ms |
| Latency Reduction | 94.3% |
| Est. Cost Savings | 40% |

## Features

- **Semantic search** — matches paraphrased queries using sentence embeddings
- **Cross-encoder reranking** — two-stage retrieval: fast FAISS + precise ms-marco reranking
- **Adaptive threshold** — dynamic similarity cutoff by query type (factual vs explanatory)
- **Query normalization** — punctuation removal + abbreviation expansion (ML → machine learning)
- **Persistent cache** — FAISS index and Redis survive Docker restarts via named volumes
- **TTL per query type** — explanations cached 24h, facts cached 1h
- **Cache invalidation** — DELETE /cache and DELETE /cache/{key} endpoints
- **Analytics** — /stats endpoint with hit rate, latency breakdown, cost savings
- **Async LLM calls** — non-blocking Groq API via AsyncGroq

## Tech Stack

Python, FastAPI, FAISS, sentence-transformers, Redis, Groq, Docker

## Quick Start

```bash
git clone https://github.com/kaipbergen/semantic-cache
cd semantic-cache
cp .env.example .env
# Add GROQ_API_KEY to .env
docker-compose up --build
```

## API Endpoints

```
POST   /query          — semantic cache lookup + LLM fallback
GET    /stats          — cache analytics
GET    /health         — health check
DELETE /cache          — clear all cache
DELETE /cache/{key}    — delete specific entry
```

## Benchmarks

```bash
python3 -m venv venv && source venv/bin/activate
pip install httpx
python3 tests/benchmark.py
```