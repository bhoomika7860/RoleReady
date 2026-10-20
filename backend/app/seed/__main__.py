import argparse
import sys

from app.core.db import session_factory
from app.seed.loader import SeedError, catalogue_empty, seed


def main() -> int:
    parser = argparse.ArgumentParser(description="Load RoleReady catalogue content (idempotent).")
    parser.add_argument("--if-empty", action="store_true", help="only seed when no roles exist")
    args = parser.parse_args()
    with session_factory()() as db:
        if args.if_empty and not catalogue_empty(db):
            print("catalogue already seeded; skipping")
            return 0
        try:
            counts = seed(db)
        except SeedError as exc:
            db.rollback()
            print(f"SEED FAILED: {exc}", file=sys.stderr)
            return 1
    for k, v in counts.items():
        print(f"{k:>22}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
