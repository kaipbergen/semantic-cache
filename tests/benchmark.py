import httpx
import asyncio
import time

BASE_URL = "http://localhost:8000"

# First pass - populate cache
SEED_QUERIES = [
    "What is machine learning?",
    "What is artificial intelligence?",
    "What is natural language processing?",
    "What is deep learning?",
    "What is the capital of France?",
    "How does photosynthesis work?",
    "What is the speed of light?",
    "Who invented the telephone?",
    "What is quantum computing?",
    "What is Python programming language?",
]

# Second pass - similar queries that should hit cache
SIMILAR_QUERIES = [
    "Explain machine learning to me",
    "Can you explain what machine learning is?",
    "Tell me about ML",
    "Describe artificial intelligence",
    "What does AI mean?",
    "Tell me about artificial intelligence",
    "Explain NLP to me",
    "What is NLP used for?",
    "Explain deep learning",
    "How does deep learning work?",
    "What's the capital city of France?",
    "Capital of France?",
    "How do plants make food?",
    "Explain photosynthesis",
    "How fast is light?",
    "Speed of light value",
    "Who made the first telephone?",
    "Telephone invention history",
    "Explain quantum computing",
    "What is quantum computer?",
]

async def run_benchmark():
    async with httpx.AsyncClient(timeout=60) as client:
        print("=" * 60)
        print("SEMANTIC CACHE BENCHMARK")
        print("=" * 60)

        # Clear cache first
        await client.delete(f"{BASE_URL}/cache")
        print("\n[Phase 1] Populating cache with seed queries...")
        print("-" * 60)

        for query in SEED_QUERIES:
            response = await client.post(f"{BASE_URL}/query", json={"prompt": query})
            await asyncio.sleep(1)
            data = response.json()
            print(f"[SEED] {query[:50]:<50} | {data['latency_ms']:.0f}ms")

        print(f"\n[Phase 2] Testing semantic cache hits...")
        print("-" * 60)

        hits = 0
        misses = 0

        for query in SIMILAR_QUERIES:
            response = await client.post(f"{BASE_URL}/query", json={"prompt": query})
            await asyncio.sleep(1)
            data = response.json()
            status = "HIT " if data["cached"] else "MISS"
            if data["cached"]:
                hits += 1
            else:
                misses += 1
            sim = f"{data.get('similarity', 0):.3f}" if data.get("similarity") else "N/A"
            print(f"[{status}] {query[:48]:<48} | sim={sim} | {data['latency_ms']:.0f}ms")

        stats_response = await client.get(f"{BASE_URL}/stats")
        stats = stats_response.json()

        print("\n" + "=" * 60)
        print("BENCHMARK RESULTS (Phase 2 only)")
        print("=" * 60)
        print(f"Similar queries tested:   {len(SIMILAR_QUERIES)}")
        print(f"Cache Hits:               {hits}")
        print(f"Cache Misses:             {misses}")
        print(f"Hit Rate:                 {hits/len(SIMILAR_QUERIES)*100:.1f}%")
        print(f"Avg Cached Latency:       {stats['avg_cached_latency_ms']}ms")
        print(f"Avg LLM Latency:          {stats['avg_llm_latency_ms']}ms")
        print(f"Latency Reduction:        {stats['latency_reduction_percent']}%")
        print(f"Est. Cost Savings:        {stats['estimated_cost_savings_percent']}%")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_benchmark())