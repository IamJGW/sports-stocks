"""The overnight update against the online database: python3 tools/nightly.py --online.

The Milestone 1 code (engine/nightly.py, pricing.py) still does the scoring, payouts, fair values and re-checks: the
robot copies the season's shared rows into an in-memory save, runs that code on it a day at a time, and sends each
day's new rows to the database in one call (robot_day in db/migrations/005_robot.sql), which puts the whole day in
or none of it. Dividends are worked out here too (nightly.dividend_cents) from each league's holdings at record
time; the database recounts the shares before inserting them, and the robot reads them back and checks them again.

Every run, in order: bring the schedule up to date; each day not yet processed (a day that can't be paid stops the
run and holds back the days after it); close leagues past their end date; the daily self-check in every league;
the status row the banner reads. Returns 0 when all is well, 1 when it stopped (the status row and output say why).
"""
import json
from datetime import timedelta

from . import ledger as L
from . import nightly as N
from .online import OnlineError


class Stopped(Exception):
    """The run can't go on. The message is what the status row and the failure email say."""


def _utc(text):
    """A time read from the database ('2026-10-25T17:00:00+00:00', maybe with a fraction) as the save's UTC text."""
    return None if text is None else L.utc_text(L.parse_utc(text[:19]))


def _num(text):
    return None if text is None else float(text)


def mirror(project, season):
    """The season's shared rows in an in-memory save (Milestone 1 tables, ESPN ids), and the games set aside.
    Read through robot_season, which sends every number exactly."""
    d = project.rpc("robot_season", p_season=season)
    s = d["season"]
    if not s:
        raise Stopped(f"No season {season} in the database.")
    conn = L.connect(":memory:")
    conn.execute("BEGIN")
    for key in ("season", "sport", "economy", "created_at"):
        L.set_meta(conn, key, s[key])
    L.set_meta(conn, "rate", float(s["rate"]))
    for a in d["athletes"]:
        conn.execute("INSERT INTO athletes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (a["espn_id"], a["ticker"], a["name"], a["team"], a["pos"], a["grp"], float(a["prior_ppg"]),
                      float(a["prior_ptg"]), float(a["start_price"]), float(a["step_shares"]), float(a["fair_value"])))
    for g in d["groups"]:
        conn.execute("INSERT INTO groups VALUES (?,?)", (g["name"], float(g["multiplier"])))
    for c in d["group_checks"]:
        conn.execute("INSERT INTO group_checks VALUES (?,?,?,?,?,?)", (c["week"], c["grp"], _num(c["actual"]),
                     _num(c["promised"]), _num(c["ratio"]), float(c["multiplier"])))
    set_aside = set()
    for g in d["games"]:
        conn.execute("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?)",
                     (g["espn_id"], g["week"], _utc(g["kickoff"]), g["day"], g["home"], g["away"], int(g["playoff"]),
                      g["status"], _utc(g["processed_at"])))
        if g["set_aside_at"] and not g["processed_at"]:
            set_aside.add(g["espn_id"])
    for r in d["stat_lines"]:
        conn.execute("INSERT INTO stat_lines VALUES (?,?,?,?,?)",
                     (r["game_id"], r["athlete_id"], r["team"], json.dumps(r["stats"]), float(r["points"])))
    conn.execute("COMMIT")
    return conn, set_aside


def push_schedule(project, season, conn):
    """Send every unprocessed game's kickoff, teams and status (the database changes only what differs)."""
    games = [{"espn_id": g["id"], "week": g["week"], "kickoff": g["kickoff"], "day": g["day"], "home": g["home"],
              "away": g["away"], "status": g["status"]}
             for g in conn.execute("SELECT * FROM games WHERE processed_at IS NULL")]
    return project.rpc("robot_sync_games", p_season=season, p_games=games)


def day_rows(project, season, conn, day, parsed, report):
    """What robot_day needs for a day the in-memory save has just processed."""
    pre = season + ":"
    ids = [g["id"] for g, _ in parsed]
    marks = ",".join("?" * len(ids))
    q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a)]  # noqa: E731
    rate = L.meta(conn, "rate")
    payouts = q(f"SELECT * FROM payouts WHERE game_id IN ({marks})", *ids)
    holders = {}
    for h in project.rpc("robot_holders", p_season=season, p_day=day):
        holders.setdefault(h["athlete_id"], []).append(h)
    dividends = []
    for p in payouts:
        for h in holders.get(pre + p["athlete_id"], []):
            dividends.append({"market_id": h["market_id"], "game_id": pre + p["game_id"], "athlete_id": h["athlete_id"],
                              "member_id": h["member_id"], "shares": h["shares"],
                              "cents": N.dividend_cents(h["shares"], p["points"], rate, p["boost"])})
    weeks = sorted({c["week"] for c in report["group_checks"]})
    shared = {k: v for k, v in report.items() if k not in ("players", "busiest")}
    return {
        "games": [pre + i for i in ids],
        "stat_lines": [{**s, "game_id": pre + s["game_id"], "athlete_id": pre + s["athlete_id"],
                        "stats": json.loads(s["stats"])}
                       for s in q(f"SELECT * FROM stat_lines WHERE game_id IN ({marks})", *ids)],
        "payouts": [{"game_id": pre + p["game_id"], "athlete_id": pre + p["athlete_id"], "points": p["points"],
                     "boost": p["boost"], "per_share": p["per_share"]} for p in payouts],
        "dividends": dividends,
        "athletes": [{"id": pre + a["id"], "team": a["team"], "fair_value": a["fair_value"]}
                     for a in q("SELECT id, team, fair_value FROM athletes")],
        "groups": q("SELECT name, multiplier FROM groups"),
        "group_checks": [c for w in weeks for c in q("SELECT * FROM group_checks WHERE week = ?", w)],
        "fair_values": [{"athlete_id": pre + f["athlete_id"], "fair_value": f["fair_value"]}
                        for f in q("SELECT athlete_id, fair_value FROM fair_values WHERE day = ?", day)],
        "report": shared,
    }


def read_back(project, rows):
    """After a day is in: the dividends and payouts stored are exactly the ones sent."""
    games = "in.(" + ",".join(f'"{g}"' for g in rows["games"]) + ")"
    key = lambda d: (d["market_id"], d["game_id"], d["athlete_id"], d["member_id"])  # noqa: E731
    sent = {key(d): (d["shares"], d["cents"]) for d in rows["dividends"]}
    got = {key(d): (d["shares"], d["cents"]) for d in project.select("dividends", game_id=games)}
    problems = []
    if sent != got:
        problems.append(f"dividends: sent {len(sent)}, stored {len(got)}, "
                        f"{len(set(sent.items()) ^ set(got.items()))} differ")
    sent = {(p["game_id"], p["athlete_id"]): p["per_share"] for p in rows["payouts"]}
    got = {(p["game_id"], p["athlete_id"]): p["per_share"] for p in project.select("payouts", game_id=games)}
    if sent.keys() != got.keys() or any(abs(sent[k] - got[k]) > 1e-12 * max(1.0, abs(sent[k])) for k in sent):
        problems.append("payouts don't match what was sent")
    return problems


def leagues_to_check(project, season, now):
    """Every league trading this season that is open or closed in the last week."""
    since = (now - timedelta(days=7)).isoformat()
    return [m["id"] for m in project.select("markets", seasons=f"cs.{{{season}}}",
                                            **{"or": f"(closed_at.is.null,closed_at.gt.{since})"}, order="id")]


def run(project, season, feed, now, offline=False, quiet=False, log=print, weeks=range(1, 19)):
    """One run of the online robot. now: the moment it runs as (Eastern 'today' comes from it)."""
    today = L.eastern_day(now)
    stopped_on = reason = None
    try:
        conn, set_aside = mirror(project, season)
        N.sync_schedule(conn, feed, weeks=weeks, offline=offline)
        changed = push_schedule(project, season, conn)
        if changed:
            log(f"Schedule: {changed} game(s) added or changed.")
        days = N.days_to_process(conn, today)
        if not days:
            log("Nothing new to process: every finished game is already paid.")
        for day in days:
            try:
                parsed = N.fetch_day(conn, day, feed, offline=offline, set_aside=set_aside)
            except N.NotReady as e:
                stopped_on, reason = day, str(e)
                log(f"Stopped at {day}; nothing paid for it:\n{e}")
                break
            if not parsed:
                log(f"{day}: only set-aside games left, still waiting on a good box score.")
                continue
            report = N.process_day(conn, day, parsed, now)
            rows = day_rows(project, season, conn, day, parsed, report)
            try:
                got = project.rpc("robot_day", p_season=season, p_day=day, p=rows)
            except OnlineError as e:
                stopped_on, reason = day, f"The database refused {day}'s update: {e}"
                log(f"Stopped at {day}; nothing paid for it:\n{reason}")
                break
            if got.get("skipped"):
                log(f"{day}: already in (another run did it).")
                continue
            problems = read_back(project, rows)
            if problems:
                raise Stopped(f"{day} is in, but reading it back found: " + "; ".join(problems))
            if quiet:
                log(f"{day}: {got['games']} games, dividends ${got['dividend_cents'] / 100:,.2f} in "
                    f"{got['reports']} league(s), {got['fills']} overnight fill(s)"
                    + (f", group re-check after week {report['group_checks'][0]['week']}"
                       if report["group_checks"] else ""))
            else:
                log(N.report_text(report) + f"\n\nDividends ${got['dividend_cents'] / 100:,.2f} in {got['reports']} "
                    f"league(s); {got['fills']} order(s) filled overnight.\n")
        ended = project.rpc("end_leagues", p_today=today)
        if ended:
            log(f"Leagues ended: {len(ended)}.")
        bad = []
        for m in leagues_to_check(project, season, now):
            bad += [f"league {m}: {p['problem']} ({p['detail']})" for p in project.rpc("check_league", p_market=m)]
        if bad:
            raise Stopped("The daily self-check failed: " + "; ".join(bad[:10])
                          + (f" (and {len(bad) - 10} more)" if len(bad) > 10 else ""))
    except (Stopped, OnlineError) as e:
        reason = str(e)
        log(f"Stopped: {reason}")
    except Exception as e:  # anything unexpected still reaches the status row before the run fails
        reason = f"The robot crashed: {type(e).__name__}: {e}"
        log(reason)
        _finish(project, season, stopped_on, reason, log)
        raise
    _finish(project, season, stopped_on, reason, log)
    return 1 if reason else 0


def _finish(project, season, stopped_on, reason, log):
    try:
        project.rpc("robot_finish", p_season=season, p_stopped_on=stopped_on, p_reason=reason)
    except OnlineError as e:
        log(f"Couldn't write the status row either: {e}")

