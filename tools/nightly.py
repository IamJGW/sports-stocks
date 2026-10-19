"""The nightly job, run by hand: python3 tools/nightly.py

Fetches every finished game since the last run, checks the box scores, pays dividends, updates fair values, runs
the weekly group re-check after each NFL week, and writes the market report (also saved in save/reports/).

Options:
  --as-of 2026-10-12   run as if it were 4 a.m. Eastern that morning (for catching up or replaying)
  --offline            use only saved box scores, download nothing
  --save PATH          a different save file (default save/game.sqlite)
If a game isn't final or its box score doesn't add up, the job stops, pays nothing for that day, and says why.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from adapters import espn_nfl as feed  # noqa: E402
from engine import ledger as L, nightly as N, pricing  # noqa: E402
from tools import hand_check  # noqa: E402

DEFAULT_SAVE = os.path.join(ROOT, "save", "game.sqlite")


def as_of(text):
    y, m, d = map(int, text.split("-"))
    return datetime(y, m, d, 4, 0, tzinfo=L.EASTERN).astimezone(timezone.utc)


def check_corrections(conn, week):
    """Download a finished week's box scores again and list any athlete whose points have changed since we paid."""
    notes = []
    weights = L.economy(conn)["sports"]["NFL"]["scoring"]
    for g in conn.execute("SELECT id, home, away FROM games WHERE week = ? AND processed_at IS NOT NULL", (week,)):
        p = feed.parse_game(feed.fresh_game_summary(g["id"]))
        for r in conn.execute("SELECT s.athlete_id, s.points, a.ticker FROM stat_lines s JOIN athletes a "
                              "ON a.id = s.athlete_id WHERE s.game_id = ?", (g["id"],)):
            line = p["lines"].get(r["athlete_id"])
            now_pts = round(pricing.score({k: line[k] for k in weights}, weights), 2) if line else 0.0
            if abs(now_pts - r["points"]) > 0.005:
                notes.append(f"{r['ticker']} ({g['away']} at {g['home']}): paid on {r['points']:.2f} pts, "
                             f"ESPN now says {now_pts:.2f}. Not changed (Milestone 1 pays once).")
    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--save", default=DEFAULT_SAVE)
    ap.add_argument("--quiet", action="store_true", help="print only a one-line summary per day")
    args = ap.parse_args()
    if not os.path.exists(args.save):
        sys.exit("No game yet. Start one with: python3 tools/new_game.py")
    now = as_of(args.as_of) if args.as_of else datetime.now(timezone.utc)
    conn = L.connect(args.save)
    N.sync_schedule(conn, feed, offline=args.offline)
    days = N.days_to_process(conn, L.eastern_day(now))
    if not days:
        print("Nothing new to process: every finished game is already paid.")
    reports = os.path.join(os.path.dirname(os.path.abspath(args.save)), "reports")
    os.makedirs(reports, exist_ok=True)
    weeks = []
    for day in days:
        try:
            parsed = N.fetch_day(conn, day, feed, offline=args.offline)
        except N.NotReady as e:
            print(f"Stopped at {day}; nothing paid for it:\n{e}")
            sys.exit(1)
        report = N.process_day(conn, day, parsed, now)
        text = N.report_text(report)
        # Stat corrections usually land within a few days, so when a week finishes, look at the week before it.
        recent = (now - L.parse_utc(L.record_time(day))).days <= 3  # not while catching up on old weeks
        if report["group_checks"] and recent and not args.offline and not args.as_of:
            week = report["group_checks"][0]["week"] - 1
            if week >= 1:
                notes = check_corrections(conn, week)
                text += "\n\nStat corrections for week %d: %s" % (week, "\n  " + "\n  ".join(notes) if notes else "none")
        week = conn.execute("SELECT MAX(week) FROM games WHERE day = ?", (day,)).fetchone()[0]
        if week not in weeks:
            weeks.append(week)
        with open(os.path.join(reports, f"{day}.txt"), "w") as f:
            f.write(text + "\n")
        if args.quiet:
            paid = sum(p["dividend_cents"] for p in report["players"])
            print(f"{day}: {len(report['games'])} games, dividends ${paid / 100:,.2f}"
                  + (f", group re-check after week {report['group_checks'][0]['week']}" if report["group_checks"] else ""))
        else:
            print(text + "\n")
    write_hand_checks(conn, weeks, args.save)


def write_hand_checks(conn, weeks, save):
    """One hand-check workbook per week touched by this run (written once, after the last day, to stay quick)."""
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(save))), "checks")
    for week in weeks:
        try:
            path = hand_check.write_week(conn, week, out)
            if path and hand_check.recalculate(path):
                lines, bad = hand_check.results(path)
                print(f"Hand check, week {week}: {os.path.relpath(path, ROOT)} ({lines} lines, "
                      + (f"{bad} MISMATCHES, look at them)" if bad else "all match)"))
            elif path:
                print(f"Hand check, week {week}: {os.path.relpath(path, ROOT)} (not recalculated; Excel will do it)")
        except Exception as e:  # the books are already safe; a workbook problem must not hide the night's report
            print(f"Hand check for week {week} failed: {e}")


if __name__ == "__main__":
    main()
