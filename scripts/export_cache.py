import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def export_jsonl(jsonl_path: str, prompt_store, redis_client, decode_payload) -> tuple[int, int]:
    exported = 0
    skipped = 0
    with open(jsonl_path, "w") as f:
        for prompt in prompt_store:
            raw = redis_client.get(prompt)
            if raw is None:
                skipped += 1
                continue
            response = decode_payload(raw)
            f.write(json.dumps({"prompt": prompt, "response": response}) + "\n")
            exported += 1
    return exported, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Export cached prompt/response pairs to a JSONL file "
        '(one {"prompt": ..., "response": ...} object per line) for '
        "inspection or debugging."
    )
    parser.add_argument("jsonl_path", help="Path to write the JSONL file to")
    args = parser.parse_args()

    from app.cache import _decode_payload, prompt_store, redis_client

    exported, skipped = export_jsonl(args.jsonl_path, prompt_store, redis_client, _decode_payload)
    print(f"Exported {exported} entries, skipped {skipped} with no live Redis value")


if __name__ == "__main__":
    main()
