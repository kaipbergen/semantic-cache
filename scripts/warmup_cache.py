import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_jsonl(jsonl_path: str, store_cache) -> tuple[int, int]:
    loaded = 0
    skipped = 0
    with open(jsonl_path) as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                prompt = entry["prompt"]
                response = entry["response"]
            except (json.JSONDecodeError, KeyError) as exc:
                print(f"skipping line {line_number}: {exc}", file=sys.stderr)
                skipped += 1
                continue
            if not prompt.strip():
                print(f"skipping line {line_number}: empty prompt", file=sys.stderr)
                skipped += 1
                continue
            store_cache(prompt, response)
            loaded += 1
    return loaded, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Preload the FAISS index + Redis from a JSONL file of "
        '{"prompt": ..., "response": ...} pairs.'
    )
    parser.add_argument("jsonl_path", help="Path to the JSONL file")
    args = parser.parse_args()

    from app.cache import store_cache

    loaded, skipped = load_jsonl(args.jsonl_path, store_cache)
    print(f"Loaded {loaded} entries, skipped {skipped}")


if __name__ == "__main__":
    main()
