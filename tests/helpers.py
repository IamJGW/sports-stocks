"""Shared test setup: a fresh in-memory market and a fake feed, so tests never touch the network or the real save."""
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import ledger as L, pricing  # noqa: E402

ECON = json.load(open(os.path.join(ROOT, "config", "economy.json")))


def utc(y, mo, d, h=12, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def eastern(y, mo, d, h=12, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=L.EASTERN).astimezone(timezone.utc)


def new_market():
    conn = L.connect(":memory:")
    L.create_game(conn, ECON, pricing.load_csv(os.path.join(ROOT, "data", "nfl_2025.csv")), "NFL", 2026,
                  "you", "Tester", utc(2026, 9, 1))
    return conn


class FakeFeed:
    """Stands in for adapters.espn_nfl: games and box scores are whatever the test puts in."""

    class FeedError(Exception):
        pass

    def __init__(self):
        self.weeks, self.boxes = {}, {}

    def add_game(self, gid, week, kickoff_utc, home, away, lines, status="STATUS_FINAL", problems=()):
        self.weeks.setdefault(week, []).append({"id": gid, "week": week, "kickoff": L.utc_text(kickoff_utc),
                                                "home": home, "away": away, "final": status == "STATUS_FINAL",
                                                "status": status})
        full = {}
        for aid, (team, stats) in lines.items():
            full[aid] = {"athlete_id": aid, "name": aid, "team": team,
                         **{k: 0 for k in ECON["sports"]["NFL"]["scoring"]}, **stats}
        self.boxes[gid] = {"game_id": gid, "kickoff": L.utc_text(kickoff_utc), "final": status == "STATUS_FINAL",
                           "teams": [home, away], "lines": full, "problems": list(problems)}

    def week_schedule(self, week, offline=False):
        return self.weeks.get(week, [])

    def game_summary(self, gid, offline=False):
        return self.boxes[gid]

    def parse_game(self, raw):
        return raw
