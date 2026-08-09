import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATUS_KEY_PREFIX = "status:"


def rebuild_from_redis(redis_client, index, get_embedding) -> tuple[list[str], int]:
    """Re-add every live cache entry found in Redis to `index`, in place.

    Disaster recovery path for when the FAISS index / prompt_store files are
    lost or corrupted but Redis (the actual prompt->response source of
    truth) is intact. Cache entries are stored under a key equal to the raw
    prompt text (see app.cache.store_cache), so any non-"status:" key is
    treated as a prompt to re-embed and re-add.
    """
    store = []
    skipped = 0
    for key in redis_client.scan_iter():
        prompt = key.decode() if isinstance(key, bytes) else key
        if prompt.startswith(STATUS_KEY_PREFIX):
            continue
        if redis_client.get(prompt) is None:
            skipped += 1
            continue
        emb = get_embedding(prompt)
        index.add(emb)
        store.append(prompt)
    return store, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild the FAISS index + prompt_store from Redis contents alone "
        "(disaster recovery when the index/prompt_store files are lost or corrupted)."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report counts without writing index files"
    )
    args = parser.parse_args()

    import faiss

    from app.cache import _save_index, dimension, get_embedding, redis_client

    index = faiss.IndexFlatIP(dimension)
    store, skipped = rebuild_from_redis(redis_client, index, get_embedding)
    print(f"Rebuilt index with {len(store)} entries from Redis, skipped {skipped} unreadable key(s)")

    if args.dry_run:
        print("Dry run: not writing index files")
        return

    _save_index(index, store)
    print("Wrote index files")


if __name__ == "__main__":
    main()
