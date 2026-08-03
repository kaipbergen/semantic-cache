import faiss
import numpy as np
import redis
import json
import os
import re
import pickle
from sentence_transformers import SentenceTransformer, CrossEncoder
from dotenv import load_dotenv

load_dotenv()

SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", 0.85))
CROSS_ENCODER_THRESHOLD = float(os.getenv("CROSS_ENCODER_THRESHOLD", 0.5))
CACHE_TTL_SHORT = int(os.getenv("CACHE_TTL_SHORT", 3600))
CACHE_TTL_LONG = int(os.getenv("CACHE_TTL_LONG", 86400))
INDEX_DIR = os.getenv("INDEX_DIR", "/app/faiss_index")
INDEX_PATH = os.path.join(INDEX_DIR, "index.faiss")
STORE_PATH = os.path.join(INDEX_DIR, "prompt_store.pkl")

BI_ENCODER_MODEL = os.getenv("BI_ENCODER_MODEL", "multi-qa-mpnet-base-dot-v1")
CROSS_ENCODER_MODEL = os.getenv("CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Bi-encoder for fast retrieval
embedder = SentenceTransformer(BI_ENCODER_MODEL)
# Cross-encoder for precise reranking
reranker = CrossEncoder(CROSS_ENCODER_MODEL)

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

dimension = 768
stats = {
    "total_requests": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "total_cached_latency_ms": 0.0,
    "total_llm_latency_ms": 0.0,
}

def _load_index():
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    if os.path.exists(INDEX_PATH) and os.path.exists(STORE_PATH):
        idx = faiss.read_index(INDEX_PATH)
        with open(STORE_PATH, "rb") as f:
            store = pickle.load(f)
        print(f"Loaded FAISS index with {idx.ntotal} entries")
        return idx, store
    return faiss.IndexFlatIP(dimension), []

def _save_index(idx, store):
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)

    index_tmp_path = INDEX_PATH + ".tmp"
    faiss.write_index(idx, index_tmp_path)
    os.replace(index_tmp_path, INDEX_PATH)

    store_tmp_path = STORE_PATH + ".tmp"
    with open(store_tmp_path, "wb") as f:
        pickle.dump(store, f)
    os.replace(store_tmp_path, STORE_PATH)

index, prompt_store = _load_index()

# Emoji and other pictographic symbols are stripped as whole runs and replaced
# with a space (rather than deleted like regular punctuation below), so
# "hello👍world" normalizes to "hello world" instead of gluing the
# surrounding words together.
_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "\U0000200D"
    "]+"
)

def normalize_query(text: str) -> str:
    text = text.lower().strip()
    text = _EMOJI_RE.sub(' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_embedding(text: str) -> np.ndarray:
    normalized = normalize_query(text)
    emb = embedder.encode([normalized], normalize_embeddings=True)
    return emb.astype("float32")

def get_ttl(prompt: str) -> int:
    long_keywords = ["explain", "describe", "what is", "how does", "tell me about"]
    if any(kw in prompt.lower() for kw in long_keywords):
        return CACHE_TTL_LONG
    return CACHE_TTL_SHORT

def get_adaptive_threshold(prompt: str) -> float:
    prompt_lower = prompt.lower()
    
    # Factual questions - high precision needed
    factual_patterns = ["capital", "who invented", "when was", "how many", "what year", "speed of"]
    if any(p in prompt_lower for p in factual_patterns):
        return 0.90
    
    # Definition questions - medium threshold
    definition_patterns = ["what is", "what are", "define", "meaning of"]
    if any(p in prompt_lower for p in definition_patterns):
        return 0.82
    
    # Explanation questions - lower threshold
    explanation_patterns = ["explain", "describe", "tell me about", "how does", "how do"]
    if any(p in prompt_lower for p in explanation_patterns):
        return 0.76
    
    # Default
    return 0.82

def search_cache(prompt: str):
    stats["total_requests"] += 1
    if index.ntotal == 0:
        stats["cache_misses"] += 1
        return None, None

    emb = get_embedding(prompt)
    k = min(5, index.ntotal)
    distances, indices_result = index.search(emb, k=k)

    threshold = get_adaptive_threshold(prompt)

    candidates = []
    for dist, idx in zip(distances[0], indices_result[0]):
        if dist >= threshold and idx < len(prompt_store):
            candidates.append((prompt_store[idx], float(dist)))

    if not candidates:
        stats["cache_misses"] += 1
        return None, float(distances[0][0]) if len(distances[0]) > 0 else None

    # Cross-encoder reranking
    pairs = [[prompt, candidate[0]] for candidate in candidates]
    scores = reranker.predict(pairs)

    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])
    best_prompt = candidates[best_idx][0]

    if best_score >= CROSS_ENCODER_THRESHOLD:
        cached_response = redis_client.get(best_prompt)
        if cached_response:
            redis_client.expire(best_prompt, get_ttl(best_prompt))
            stats["cache_hits"] += 1
            return json.loads(cached_response), candidates[best_idx][1]

    stats["cache_misses"] += 1
    return None, float(distances[0][0])

def store_cache(prompt: str, response: str):
    ttl = get_ttl(prompt)
    if prompt in prompt_store:
        redis_client.setex(prompt, ttl, json.dumps(response))
        return
    emb = get_embedding(prompt)
    index.add(emb)
    prompt_store.append(prompt)
    redis_client.setex(prompt, ttl, json.dumps(response))
    _save_index(index, prompt_store)

def get_stats() -> dict:
    total = stats["total_requests"]
    hits = stats["cache_hits"]
    misses = stats["cache_misses"]
    hit_rate = (hits / total * 100) if total > 0 else 0
    avg_cached_latency = stats["total_cached_latency_ms"] / hits if hits > 0 else 0
    avg_llm_latency = stats["total_llm_latency_ms"] / misses if misses > 0 else 0
    latency_reduction = (
        ((avg_llm_latency - avg_cached_latency) / avg_llm_latency * 100)
        if avg_llm_latency > 0 else 0
    )
    return {
        "total_requests": total,
        "cache_hits": hits,
        "cache_misses": misses,
        "hit_rate_percent": round(hit_rate, 1),
        "avg_cached_latency_ms": round(avg_cached_latency, 1),
        "avg_llm_latency_ms": round(avg_llm_latency, 1),
        "latency_reduction_percent": round(latency_reduction, 1),
        "estimated_cost_savings_percent": round(hit_rate, 1),
        "total_cached_prompts": index.ntotal,
    }