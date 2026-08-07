import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from app.cache import compact_index

    removed = compact_index()
    print(f"Removed {removed} expired entries")


if __name__ == "__main__":
    main()
