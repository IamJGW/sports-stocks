"""Download 2025's NFL regular season (schedules and box scores) into data/espn_nfl_2025/ for the availability study.

Uses the game's own ESPN adapter, pointed at 2025 and a separate cache folder. Approved by Justin 2026-10-19.
Run from sports-exchange/:  python3 research/fetch_nfl_2025.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from adapters import espn_nfl as feed  # noqa: E402

feed.SEASON = 2025
feed.CACHE = os.path.join(ROOT, "data", "espn_nfl_2025")


def main():
    got = skipped = 0
    for week in range(1, 19):
        games = feed.week_schedule(week)
        for g in games:
            if not g["final"]:
                print(f"week {week}: {g['away']} at {g['home']} not final ({g['status']}), skipped")
                skipped += 1
                continue
            path = os.path.join(feed.CACHE, f"game_{g['id']}.json.gz")
            if not os.path.exists(path):
                feed.game_summary(g["id"])
                got += 1
                time.sleep(0.4)
        print(f"week {week}: {len(games)} games")
    print(f"downloaded {got} box scores, {skipped} games not final")


if __name__ == "__main__":
    main()
