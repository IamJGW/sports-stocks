"""Do NFL groups pay above their promise early in the season and below it late? (the "availability curve" study)

2025: priced from 2024 exactly as the game prices 2026 from 2025 (pricing.starting_book on data/nfl_2024.csv with
today's levers), paid from 2025's box scores (research/fetch_nfl_2025.py). 2026: the real save, opened read-only.
Run from sports-exchange/:  python3 research/availability.py
"""
import glob
import gzip
import json
import os
import sqlite3
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from adapters import espn_nfl as feed  # noqa: E402
from engine import pricing  # noqa: E402

ECON = json.load(open(os.path.join(ROOT, "config", "economy.json")))
W = ECON["sports"]["NFL"]["scoring"]
GROUPS = ("NFL QB", "NFL RB", "NFL WR/TE")


def team_games(athletes, games, lines):
    """Rows of (week, athlete id, group, prior_ptg, appeared, points) for every team game of every listed athlete.

    Same team rule as engine/nightly.season_so_far: his team in a week is the last team he played for up to then,
    else the first he played for later, else last season's team. Negative games count as zero, like dividends.
    games: [(game_id, week, home, away)]; lines: {(game_id, athlete_id): (team, points)}.
    """
    teams_by_week, week_of = defaultdict(set), {}
    for gid, wk, home, away in games:
        teams_by_week[wk].update((home, away))
        week_of[gid] = wk
    apps = defaultdict(list)
    for (gid, aid), (team, pts) in lines.items():
        if gid in week_of:
            apps[aid].append((week_of[gid], team, pts))
    rows = []
    for a in athletes:
        ap = sorted(apps.get(a["id"], []))
        by_week = defaultdict(float)
        for wk, _, p in ap:
            by_week[wk] += max(0.0, p)
        for wk in sorted(teams_by_week):
            earlier = [t for w, t, _ in ap if w <= wk]
            team = earlier[-1] if earlier else (ap[0][1] if ap else a["team"])
            if team in teams_by_week[wk]:
                rows.append({"week": wk, "id": a["id"], "group": a["group"], "prior": a["prior_ptg"],
                             "appeared": wk in by_week and any(w == wk for w, _, _ in ap), "points": by_week[wk]})
    return rows


def load_2025():
    book = pricing.starting_book(pricing.load_csv(os.path.join(ROOT, "data", "nfl_2024.csv")), ECON, "NFL")
    athletes = book["athletes"]
    listed = {a["id"] for a in athletes}
    cache = os.path.join(ROOT, "data", "espn_nfl_2025")
    feed.SEASON = 2025
    games, lines, problems = [], {}, 0
    for wk in range(1, 19):
        sched = feed.parse_schedule(feed._read_gz(os.path.join(cache, f"schedule_week{wk:02d}.json.gz")), wk)
        for g in sched:
            raw = feed._read_gz(os.path.join(cache, f"game_{g['id']}.json.gz"))
            p = feed.parse_game(raw)
            problems += len(p["problems"])
            games.append((g["id"], wk, g["home"], g["away"]))
            for aid, ln in p["lines"].items():
                if aid in listed:
                    lines[(g["id"], aid)] = (ln["team"], pricing.score({k: ln[k] for k in W}, W))
    return athletes, team_games(athletes, games, lines), problems


def load_2026():
    conn = sqlite3.connect(f"file:{os.path.join(ROOT, 'save', 'game.sqlite')}?mode=ro", uri=True)
    athletes = [{"id": i, "group": g, "prior_ptg": p, "team": t}
                for i, g, p, t in conn.execute("SELECT id, grp, prior_ptg, team FROM athletes")]
    # season_so_far falls back to the athlete's current team; for one who never played that is last season's team.
    games = list(conn.execute("SELECT id, week, home, away FROM games WHERE processed_at IS NOT NULL"))
    lines = {(g, a): (t, p) for g, a, t, p in conn.execute("SELECT game_id, athlete_id, team, points FROM stat_lines")}
    return athletes, team_games(athletes, games, lines)


def by_week(rows, group=None):
    """{week: (points, promised, team games, appearances)} for one group or all."""
    out = defaultdict(lambda: [0.0, 0.0, 0, 0])
    for r in rows:
        if group and r["group"] != group:
            continue
        o = out[r["week"]]
        o[0] += r["points"]
        o[1] += r["prior"]
        o[2] += 1
        o[3] += r["appeared"]
    return dict(sorted(out.items()))


if __name__ == "__main__":
    ath25, rows25, problems = load_2025()
    ath26, rows26 = load_2026()
    print(f"2025: {len(ath25)} listed, {len(rows25)} team games, {problems} box-score check problems")
    print(f"2026: {len(ath26)} listed, {len(rows26)} team games")
    for season, rows in (("2025", rows25), ("2026", rows26)):
        print(f"\n{season}: paid / promised by week (played share = appearances / team games)")
        print("week  " + "  ".join(f"{g[4:]:>9}" for g in GROUPS) + "   all  played  pts/appearance vs promise")
        tots = {g: by_week(rows, g) for g in GROUPS}
        allw = by_week(rows)
        for wk, (p, pr, n, ap) in allw.items():
            cells = "  ".join(f"{tots[g][wk][0] / tots[g][wk][1]:9.2f}" for g in GROUPS)
            print(f"{wk:4d}  {cells}  {p / pr:5.2f}  {ap / n:5.0%}   {p / pr * n / ap:5.2f}")
        p, pr = sum(v[0] for v in allw.values()), sum(v[1] for v in allw.values())
        n, ap = sum(v[2] for v in allw.values()), sum(v[3] for v in allw.values())
        cells = "  ".join(f"{sum(v[0] for v in tots[g].values()) / sum(v[1] for v in tots[g].values()):9.2f}"
                          for g in GROUPS)
        print(f"  all {cells}  {p / pr:5.2f}  {ap / n:5.0%}   {p / pr * n / ap:5.2f}")
