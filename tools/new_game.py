"""Start a new Sports Stocks market (Milestone 1: solo, NFL 2026, priced from the 2025 season).

Usage (from sports-exchange/):  python3 tools/new_game.py [--save save/game.sqlite] [--name Justin]
Then run  python3 tools/nightly.py  to catch up on the games played so far this season.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import ledger as L, pricing  # noqa: E402

DEFAULT_SAVE = os.path.join(ROOT, "save", "game.sqlite")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default=DEFAULT_SAVE)
    ap.add_argument("--name", default="Justin")
    args = ap.parse_args()
    if os.path.exists(args.save):
        sys.exit(f"{os.path.relpath(args.save, ROOT)} already exists. Move or delete it first to start over.")
    os.makedirs(os.path.dirname(args.save), exist_ok=True)
    with open(os.path.join(ROOT, "config", "economy.json")) as f:
        econ = json.load(f)
    conn = L.connect(args.save)
    L.create_game(conn, econ, pricing.load_csv(os.path.join(ROOT, "data", "nfl_2025.csv")), "NFL", 2026,
                  "you", args.name, datetime.now(timezone.utc))
    n = conn.execute("SELECT COUNT(*) FROM athletes").fetchone()[0]
    print(f"New market in {os.path.relpath(args.save, ROOT)}: {n} NFL athletes, "
          f"${econ['starting_cash']:,.0f} for {args.name}. Next: python3 tools/nightly.py")


if __name__ == "__main__":
    main()
