import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.cache import search_cache, store_cache, get_stats, stats, redis_client
from app.llm import call_llm

app = FastAPI(title="Semantic Cache API")

class PromptRequest(BaseModel):
    prompt: str

class PromptResponse(BaseModel):
    response: str
    cached: bool
    similarity: float | None
    latency_ms: float

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/query", response_model=PromptResponse)
async def query(request: PromptRequest):
    start = time.time()

    cached_response, similarity = search_cache(request.prompt)

    if cached_response:
        latency = (time.time() - start) * 1000
        stats["total_cached_latency_ms"] += latency
        return PromptResponse(
            response=cached_response,
            cached=True,
            similarity=round(float(similarity), 3),
            latency_ms=round(latency, 2)
        )

    response = await call_llm(request.prompt)
    store_cache(request.prompt, response)

    latency = (time.time() - start) * 1000
    stats["total_llm_latency_ms"] += latency
    return PromptResponse(
        response=response,
        cached=False,
        similarity=round(float(similarity), 3) if similarity else None,
        latency_ms=round(latency, 2)
    )

@app.get("/stats")
def get_cache_stats():
    return get_stats()

@app.delete("/cache")
def clear_cache():
    from app.cache import index, prompt_store, _save_index
    index.reset()
    # Reinitialize with correct dimension
    import faiss
    new_index = faiss.IndexFlatIP(768)
    import app.cache as cache_module
    cache_module.index = new_index
    cache_module.prompt_store.clear()
    redis_client.flushdb()
    _save_index(cache_module.index, cache_module.prompt_store)
    return {"message": "Cache cleared", "deleted": "all"}

@app.delete("/cache/{prompt_hash}")
def delete_cache_entry(prompt_hash: str):
    deleted = redis_client.delete(prompt_hash)
    if deleted:
        return {"message": "Deleted cache entry", "key": prompt_hash}
    raise HTTPException(status_code=404, detail="Cache entry not found")