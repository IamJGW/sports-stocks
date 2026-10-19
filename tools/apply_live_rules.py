"""Copy the in-season levers (the Live Rules sheet) from config/economy.json into an existing save.

A save keeps its own copy of the levers from the day it was started, so a change on the Live Rules sheet reaches a
game already under way only through this. Only the Live Rules levers are copied: starting prices, the dividend rate
and the scoring stay as the game started. Changes apply from the next nightly run; past weeks are not redone.

Usage (from sports-exchange/):  python3 tools/apply_live_rules.py [--save save/game.sqlite]
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import ledger as L  # noqa: E402

DEFAULT_SAVE = os.path.join(ROOT, "save", "game.sqlite")


def apply(conn, live):
    """Replace the save's live levers. Returns [(lever, before, after)] for the ones that changed."""
    econ = L.economy(conn)
    before = econ.get("live", {})
    changed = [(k, before.get(k), live.get(k)) for k in sorted(set(before) | set(live)) if before.get(k) != live.get(k)]
    if changed:
        econ["live"] = live
        conn.execute("BEGIN IMMEDIATE")
        L.set_meta(conn, "economy", econ)
        conn.execute("COMMIT")
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default=DEFAULT_SAVE)
    args = ap.parse_args()
    if not os.path.exists(args.save):
        sys.exit(f"No save at {args.save}")
    with open(os.path.join(ROOT, "config", "economy.json")) as f:
        live = json.load(f)["live"]
    backup = f"{args.save}.before-live-rules-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(args.save, backup)
    changed = apply(L.connect(args.save), live)
    if not changed:
        os.remove(backup)
        print("The save already has these live rules; nothing changed.")
        return
    for k, a, b in changed:
        print(f"{k}: {a} -> {b}")
    print(f"Copy of the save before the change: {os.path.relpath(backup, ROOT)}")


if __name__ == "__main__":
    main()
