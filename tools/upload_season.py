"""Copy the season so far from the Mac's save to a Supabase project, so the online game starts caught up.

  python3 tools/upload_season.py test           copy to the test project
  python3 tools/upload_season.py live           copy to the real one
  --save PATH                                   a different save (default save/game.sqlite)

Copies only what every league shares: the season and its levers, athletes, groups and their re-checks, the schedule,
stat lines, per-share payouts and daily fair values. Justin's own solo trades and dividends stay on the Mac.
Safe to run again: rows already there are kept (stat lines and payouts can't change anyway); athletes, groups and
games take the save's latest values. Afterwards it reads everything back and checks it matches exactly.
"""
import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import ledger as L  # noqa: E402
from engine.online import OnlineError, Project  # noqa: E402

DEFAULT_SAVE = os.path.join(ROOT, "save", "game.sqlite")


def season_rows(conn):
    """Everything to upload, as {table: rows} in the online tables' shape."""
    sport, season = L.meta(conn, "sport"), L.meta(conn, "season")
    sid = f"{sport.lower()}-{season}"
    gid = lambda espn: f"{sid}:{espn}"  # noqa: E731
    q = lambda sql: [dict(r) for r in conn.execute(sql)]  # noqa: E731
    out = {
        "seasons": [{"id": sid, "sport": sport, "season": season, "rate": L.meta(conn, "rate"),
                     "economy": L.meta(conn, "economy"), "created_at": L.meta(conn, "created_at")}],
        "athletes": [{**a, "id": gid(a["id"]), "season_id": sid, "espn_id": a["id"]} for a in q("SELECT * FROM athletes")],
        "groups": [{**g, "season_id": sid} for g in q("SELECT * FROM groups")],
        "group_checks": [{**g, "season_id": sid} for g in q("SELECT * FROM group_checks")],
        "games": [{**g, "id": gid(g["id"]), "season_id": sid, "espn_id": g["id"], "playoff": bool(g["playoff"])}
                  for g in q("SELECT * FROM games")],
        "stat_lines": [{**s, "game_id": gid(s["game_id"]), "athlete_id": gid(s["athlete_id"]),
                        "stats": json.loads(s["stats"])} for s in q("SELECT * FROM stat_lines")],
        "payouts": [{**p, "game_id": gid(p["game_id"]), "athlete_id": gid(p["athlete_id"])}
                    for p in q("SELECT * FROM payouts")],
        "fair_values": [{**f, "athlete_id": gid(f["athlete_id"])} for f in q("SELECT * FROM fair_values")],
    }
    return sid, out


# table: (conflict columns, what to do with a row that's already there)
PLAN = [
    ("seasons", "id", "ignore"),
    ("athletes", "id", "merge"),
    ("groups", "season_id,name", "merge"),
    ("group_checks", "season_id,week,grp", "ignore"),
    ("games", "id", "merge"),
    ("stat_lines", "game_id,athlete_id", "ignore"),
    ("payouts", "game_id,athlete_id", "ignore"),
    ("fair_values", "day,athlete_id", "ignore"),
]
KEYS = {t: c.split(",") for t, c, _ in PLAN}


def same(a, b):
    """A value read back equals the one sent (times come back as +00:00 rather than Z)."""
    if isinstance(a, str) and isinstance(b, str) and a.endswith("Z"):
        return L.parse_utc(a) == L.parse_utc(b[:19])
    return a == b


def check(project, sid, rows):
    problems = []
    for table, sent in rows.items():
        filt = {"id": f"eq.{sid}"} if table == "seasons" else (
            {"season_id": f"eq.{sid}"} if sent and "season_id" in sent[0] else {})
        if table in ("stat_lines", "payouts"):
            filt = {"game_id": f"like.{sid}:*"}
        if table == "fair_values":
            filt = {"athlete_id": f"like.{sid}:*"}
        got = {tuple(str(r[k]) for k in KEYS[table]): r for r in project.select(table, **filt)}
        for s in sent:
            g = got.get(tuple(str(s[k]) for k in KEYS[table]))
            if g is None:
                problems.append(f"{table}: missing {[s[k] for k in KEYS[table]]}")
                continue
            for col, v in s.items():
                if col != "economy" and not same(v, g[col]):
                    problems.append(f"{table} {[s[k] for k in KEYS[table]]}: {col} sent {v!r}, stored {g[col]!r}")
        if len(got) != len(sent):
            problems.append(f"{table}: sent {len(sent)} rows, the project has {len(got)}")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", choices=["test", "live"])
    ap.add_argument("--save", default=DEFAULT_SAVE)
    args = ap.parse_args()
    conn = sqlite3.connect(args.save)
    conn.row_factory = sqlite3.Row
    sid, rows = season_rows(conn)
    try:
        project = Project(args.target)
        for table, conflict, existing in PLAN:
            project.insert(table, rows[table], on_conflict=conflict, existing=existing)
            print(f"{table}: {len(rows[table])} rows")
        problems = check(project, sid, rows)
    except OnlineError as e:
        sys.exit(f"Supabase said: {e}")
    if problems:
        print(f"Read back: {len(problems)} differences. First few:")
        for p in problems[:10]:
            print("  " + p)
        sys.exit(1)
    print(f"Read back: {sid} matches the save exactly.")


if __name__ == "__main__":
    main()
