import faiss
import numpy as np
import redis
import gzip
import json
import os
import re
import pickle
from sentence_transformers import SentenceTransformer, CrossEncoder
from dotenv import load_dotenv

from app.logging_config import configure_logging, get_logger

load_dotenv()
configure_logging()
logger = get_logger(__name__)

SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", 0.85))
CROSS_ENCODER_THRESHOLD = float(os.getenv("CROSS_ENCODER_THRESHOLD", 0.5))
CACHE_TTL_SHORT = int(os.getenv("CACHE_TTL_SHORT", 3600))
CACHE_TTL_LONG = int(os.getenv("CACHE_TTL_LONG", 86400))
MAX_CACHE_SIZE = int(os.getenv("MAX_CACHE_SIZE", 0))
COMPRESSION_THRESHOLD_BYTES = int(os.getenv("COMPRESSION_THRESHOLD_BYTES", 1024))
INDEX_DIR = os.getenv("INDEX_DIR", "/app/faiss_index")
INDEX_PATH = os.path.join(INDEX_DIR, "index.faiss")
STORE_PATH = os.path.join(INDEX_DIR, "prompt_store.pkl")
INDEX_METADATA_PATH = os.path.join(INDEX_DIR, "index_metadata.json")

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
    "category_counts": {"factual": 0, "definition": 0, "explanation": 0, "default": 0},
}

def _load_index():
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    if os.path.exists(INDEX_PATH) and os.path.exists(STORE_PATH):
        stored_model = None
        if os.path.exists(INDEX_METADATA_PATH):
            with open(INDEX_METADATA_PATH) as f:
                stored_model = json.load(f).get("bi_encoder_model")
        if stored_model is not None and stored_model != BI_ENCODER_MODEL:
            # Vectors on disk were produced by a different bi-encoder and are
            # not comparable to embeddings from the current one (different
            # geometry, possibly different dimension) - start fresh rather
            # than serving similarity scores computed against stale vectors.
            logger.warning(
                "Index was built with bi-encoder '%s', current is '%s' - discarding stale index",
                stored_model,
                BI_ENCODER_MODEL,
            )
            return faiss.IndexFlatIP(dimension), []
        idx = faiss.read_index(INDEX_PATH)
        with open(STORE_PATH, "rb") as f:
            store = pickle.load(f)
        if idx.ntotal != len(store):
            # A crash or partial write between the index and store files can
            # leave their entry counts out of sync, which corrupts the
            # positional correspondence search_cache/compact_index rely on -
            # safer to start fresh than to serve mismatched prompts.
            logger.warning(
                "Index/prompt_store size mismatch (%d vs %d entries) - discarding corrupted index",
                idx.ntotal,
                len(store),
            )
            return faiss.IndexFlatIP(dimension), []
        logger.info("Loaded FAISS index with %d entries", idx.ntotal)
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

    metadata_tmp_path = INDEX_METADATA_PATH + ".tmp"
    with open(metadata_tmp_path, "w") as f:
        json.dump({"bi_encoder_model": BI_ENCODER_MODEL}, f)
    os.replace(metadata_tmp_path, INDEX_METADATA_PATH)

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

_CATEGORY_THRESHOLDS = {
    "factual": 0.90,
    "definition": 0.82,
    "explanation": 0.76,
    "default": 0.82,
}

def get_prompt_category(prompt: str) -> str:
    prompt_lower = prompt.lower()

    # Factual questions - high precision needed
    factual_patterns = ["capital", "who invented", "when was", "how many", "what year", "speed of"]
    if any(p in prompt_lower for p in factual_patterns):
        return "factual"

    # Definition questions - medium threshold
    definition_patterns = ["what is", "what are", "define", "meaning of"]
    if any(p in prompt_lower for p in definition_patterns):
        return "definition"

    # Explanation questions - lower threshold
    explanation_patterns = ["explain", "describe", "tell me about", "how does", "how do"]
    if any(p in prompt_lower for p in explanation_patterns):
        return "explanation"

    return "default"

def get_adaptive_threshold(prompt: str) -> float:
    return _CATEGORY_THRESHOLDS[get_prompt_category(prompt)]

def search_cache(prompt: str):
    """Returns (response, similarity, reason). `reason` explains a miss
    ("empty_cache", "no_candidates", "expired", "below_threshold") or marks
    a hit ("hit")."""
    stats["total_requests"] += 1
    stats["category_counts"][get_prompt_category(prompt)] += 1
    if index.ntotal == 0:
        stats["cache_misses"] += 1
        return None, None, "empty_cache"

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
        return None, float(distances[0][0]) if len(distances[0]) > 0 else None, "no_candidates"

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
            return _decode_payload(cached_response), candidates[best_idx][1], "hit"
        stats["cache_misses"] += 1
        return None, candidates[best_idx][1], "expired"

    stats["cache_misses"] += 1
    return None, float(distances[0][0]), "below_threshold"

_GZIP_MAGIC = b"\x1f\x8b"

def _encode_payload(response) -> bytes:
    raw = json.dumps(response).encode("utf-8")
    if len(raw) > COMPRESSION_THRESHOLD_BYTES:
        return gzip.compress(raw)
    return raw

def _decode_payload(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if raw[:2] == _GZIP_MAGIC:
        raw = gzip.decompress(raw)
    return json.loads(raw)

def _evict_oldest(count: int):
    """Evict the `count` oldest entries. Insertion order is preserved as
    position 0..ntotal-1 in both `index` and `prompt_store`, and removing a
    prefix range keeps that correspondence intact (remaining entries shift
    down uniformly in both structures)."""
    if count <= 0:
        return
    index.remove_ids(faiss.IDSelectorRange(0, count))
    evicted = prompt_store[:count]
    del prompt_store[:count]
    for evicted_prompt in evicted:
        redis_client.delete(evicted_prompt)

def compact_index() -> int:
    """Drop entries whose Redis key has expired (TTL entry gone) from the
    index and prompt_store, keeping both in sync. Returns count removed."""
    expired_positions = [i for i, prompt in enumerate(prompt_store) if redis_client.ttl(prompt) == -2]
    if not expired_positions:
        return 0
    index.remove_ids(faiss.IDSelectorBatch(np.array(expired_positions, dtype=np.int64)))
    for i in reversed(expired_positions):
        del prompt_store[i]
    _save_index(index, prompt_store)
    return len(expired_positions)

def store_cache(prompt: str, response: str):
    ttl = get_ttl(prompt)
    if prompt in prompt_store:
        redis_client.setex(prompt, ttl, _encode_payload(response))
        return
    emb = get_embedding(prompt)
    index.add(emb)
    prompt_store.append(prompt)
    redis_client.setex(prompt, ttl, _encode_payload(response))
    if MAX_CACHE_SIZE > 0 and len(prompt_store) > MAX_CACHE_SIZE:
        _evict_oldest(len(prompt_store) - MAX_CACHE_SIZE)
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
        "index_dimension": dimension,
        "index_vectors_bytes": index.ntotal * dimension * 4,
        "redis_key_count": redis_client.dbsize(),
        "category_counts": dict(stats["category_counts"]),
    }