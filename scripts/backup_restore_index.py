import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def backup(index_path: str, store_path: str, metadata_path: str, dest_dir: str) -> list[str]:
    os.makedirs(dest_dir, exist_ok=True)
    copied = []
    for src in (index_path, store_path, metadata_path):
        if os.path.exists(src):
            dest = os.path.join(dest_dir, os.path.basename(src))
            shutil.copyfile(src, dest)
            copied.append(dest)
    return copied


def restore(dest_index_path: str, dest_store_path: str, dest_metadata_path: str, src_dir: str) -> list[str]:
    restored = []
    for dest in (dest_index_path, dest_store_path, dest_metadata_path):
        src = os.path.join(src_dir, os.path.basename(dest))
        if not os.path.exists(src):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp_dest = dest + ".tmp"
        shutil.copyfile(src, tmp_dest)
        os.replace(tmp_dest, dest)
        restored.append(dest)
    return restored


def main():
    parser = argparse.ArgumentParser(
        description="Backup or restore the FAISS index + prompt_store + metadata files."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="Copy the index files into a directory")
    backup_parser.add_argument("dest_dir", help="Directory to copy the index files into")

    restore_parser = subparsers.add_parser("restore", help="Copy index files from a backup directory back into place")
    restore_parser.add_argument("src_dir", help="Directory containing a previous backup")

    args = parser.parse_args()

    from app.cache import INDEX_METADATA_PATH, INDEX_PATH, STORE_PATH

    if args.command == "backup":
        copied = backup(INDEX_PATH, STORE_PATH, INDEX_METADATA_PATH, args.dest_dir)
        print(f"Backed up {len(copied)} file(s) to {args.dest_dir}")
    else:
        restored = restore(INDEX_PATH, STORE_PATH, INDEX_METADATA_PATH, args.src_dir)
        print(f"Restored {len(restored)} file(s) from {args.src_dir}")


if __name__ == "__main__":
    main()
