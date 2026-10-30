"""The overnight update: fetch box scores, check them, pay dividends, update fair values, re-check the groups weekly,
and write the market report.

Each Eastern day with games is processed once, in order, inside one database transaction: either all of a day goes
in or none of it does. Box scores are downloaded and checked before the transaction starts, so a feed problem stops
the run before any money moves.
"""
import json
from datetime import datetime, timedelta

from . import ledger as L
from . import pricing

SKIPPED = ("STATUS_POSTPONED", "STATUS_CANCELED")


class NotReady(Exception):
    """A day can't be paid yet (a game isn't final, or its box score doesn't add up). Nothing was changed."""


# ---- Schedule

def sync_schedule(conn, feed, weeks=range(1, 19), offline=False):
    """Bring every game's kickoff and status up to date. Processed games keep their processed mark."""
    conn.execute("BEGIN")
    try:
        for w in weeks:
            for g in feed.week_schedule(w, offline=offline):
                day = L.eastern_day(L.parse_utc(g["kickoff"]))
                kick = L.utc_text(L.parse_utc(g["kickoff"]))
                conn.execute("""INSERT INTO games (id, week, kickoff, day, home, away, status) VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET week = excluded.week, kickoff = excluded.kickoff, day = excluded.day,
                    home = excluded.home, away = excluded.away, status = excluded.status
                    WHERE games.processed_at IS NULL""", (g["id"], w, kick, day, g["home"], g["away"], g["status"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def days_to_process(conn, today):
    """Eastern dates before today that still have unprocessed games."""
    rows = conn.execute("SELECT DISTINCT day FROM games WHERE processed_at IS NULL AND day < ? AND status NOT IN (?, ?) "
                        "ORDER BY day", (today, *SKIPPED)).fetchall()
    return [r["day"] for r in rows]


# ---- One day

def fetch_day(conn, day, feed, offline=False, set_aside=()):
    """Download and check every game of the day. Returns parsed games, or raises NotReady with every problem found.
    A game in set_aside (set aside by hand, online only) whose box score is still bad is left out instead."""
    games = conn.execute("SELECT * FROM games WHERE day = ? AND processed_at IS NULL AND status NOT IN (?, ?)",
                         (day, *SKIPPED)).fetchall()
    parsed, problems = [], []
    listed = {r["id"] for r in conn.execute("SELECT id FROM athletes")}
    for g in games:
        found, p = check_game(g, feed, listed, offline)
        if found and g["id"] in set_aside:
            continue
        problems += found
        if p is not None:
            parsed.append((g, p))
    if problems:
        raise NotReady("\n".join(problems))
    return parsed


def check_game(g, feed, listed, offline):
    """One game's problems (none: an empty list) and its parsed box score (None if there isn't one)."""
    if g["status"] != "STATUS_FINAL":
        return [f"{g['away']} at {g['home']} isn't final yet ({g['status']})."], None
    try:
        p = feed.parse_game(feed.game_summary(g["id"], offline=offline))
    except feed.FeedError as e:
        return [str(e)], None
    problems = []
    if not p["final"]:
        problems.append(f"{g['away']} at {g['home']}: box score isn't marked final.")
    if sorted(p["teams"]) != sorted([g["home"], g["away"]]):
        problems.append(f"Game {g['id']}: box score is for {p['teams']}, schedule says {g['away']} at {g['home']}.")
    problems += [f"{g['away']} at {g['home']}: {x}" for x in p["problems"]]
    if not any(aid in listed for aid in p["lines"]):
        problems.append(f"{g['away']} at {g['home']}: no listed athlete appears in the box score.")
    return problems, p


def process_day(conn, day, parsed, now):
    """Pay a day's dividends and move prices. parsed comes from fetch_day. Returns the day's market report."""
    econ = L.economy(conn)
    sport = L.meta(conn, "sport")
    rate = L.meta(conn, "rate")
    weights = econ["sports"][sport]["scoring"]
    rec = L.record_time(day)
    paid_at = L.utc_text(now)
    athletes = {r["id"]: r for r in conn.execute("SELECT * FROM athletes")}
    before_fv = {i: a["fair_value"] for i, a in athletes.items()}
    payouts = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        for g, p in parsed:
            boost = econ["live"]["playoff_boost"] if g["playoff"] else 1.0
            for aid, line in p["lines"].items():
                if aid not in athletes:
                    continue
                stats = {k: line[k] for k in weights}
                points = round(pricing.score(stats, weights), 2)
                conn.execute("INSERT INTO stat_lines VALUES (?,?,?,?,?)",
                             (g["id"], aid, line["team"], json.dumps(stats), points))
                conn.execute("UPDATE athletes SET team = ? WHERE id = ?", (line["team"], aid))
                per_share = max(0.0, points) * rate * boost  # a bad game pays nothing; it never charges holders
                conn.execute("INSERT INTO payouts VALUES (?,?,?,?,?,?,?)",
                             (g["id"], aid, points, boost, per_share, rec, paid_at))
                total = 0
                for player, shares in L.holders_at(conn, aid, rec).items():
                    cents = dividend_cents(shares, points, rate, boost)
                    conn.execute("INSERT INTO dividends VALUES (?,?,?,?,?)", (g["id"], aid, player, shares, cents))
                    total += cents
                payouts.append({"athlete_id": aid, "points": points, "per_share": per_share, "paid_cents": total,
                                "game": f"{g['away']} at {g['home']}"})
            conn.execute("UPDATE games SET processed_at = ? WHERE id = ?", (paid_at, g["id"]))

        checks = []
        for week in weeks_just_finished(conn):
            checks += run_recheck(conn, week, econ)
        update_fair_values(conn, day, econ)
        report = make_report(conn, day, now, payouts, before_fv, checks)
        conn.execute("INSERT INTO reports VALUES (?,?,?) ON CONFLICT(day) DO UPDATE SET made_at = excluded.made_at, "
                     "body = excluded.body", (day, paid_at, json.dumps(report)))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return report


def dividend_cents(shares, points, rate, boost):
    """One holder's payout for one game, rounded once to the nearest cent (half a cent rounds up)."""
    exact = shares * max(0.0, points) * rate * boost * 100
    return int(round(exact, 6) + 0.5)


# ---- Fair values and the weekly re-check

def season_so_far(conn, through_week=None, promise_by_week=None):
    """Per listed athlete: (team games played, fantasy points so far with negative games counted as zero, promised
    games). Promised games add up each team game's weekly promise (1 for every game when there's no promise row)."""
    q = "SELECT id, week, home, away FROM games WHERE processed_at IS NOT NULL"
    if through_week is not None:
        q += f" AND week <= {int(through_week)}"
    games = conn.execute(q).fetchall()
    teams_by_week = {}
    for g in games:
        teams_by_week.setdefault(g["week"], set()).update((g["home"], g["away"]))
    week_of = {g["id"]: g["week"] for g in games}
    seen = {}  # athlete -> [(week, team, points)]
    for r in conn.execute("SELECT game_id, athlete_id, team, points FROM stat_lines"):
        if r["game_id"] in week_of:
            seen.setdefault(r["athlete_id"], []).append((week_of[r["game_id"]], r["team"], r["points"]))
    out = {}
    for a in conn.execute("SELECT id, team FROM athletes"):
        apps = sorted(seen.get(a["id"], []))
        points = sum(max(0.0, p) for _, _, p in apps)
        team_games = promised = 0
        for w, teams in teams_by_week.items():
            # His team that week: the last team he played for up to then, else the first he played for later,
            # else last season's team (an athlete who hasn't played at all this season).
            earlier = [t for wk, t, _ in apps if wk <= w]
            team = earlier[-1] if earlier else (apps[0][1] if apps else a["team"])
            if team in teams:
                team_games += 1
                promised += week_promise(promise_by_week, w)
        out[a["id"]] = (team_games, points, promised)
    return out


def update_fair_values(conn, day, econ):
    sport, rate = L.meta(conn, "sport"), L.meta(conn, "rate")
    mult = {r["name"]: r["multiplier"] for r in conn.execute("SELECT * FROM groups")}
    so_far = season_so_far(conn)
    for a in conn.execute("SELECT id, grp, prior_ptg FROM athletes").fetchall():
        tg, pts, _ = so_far[a["id"]]
        ptg = pricing.expected_ptg(a["prior_ptg"], mult[a["grp"]], pts, tg, econ)
        fv = max(0.01, pricing.fair_value(ptg, rate, econ, sport))
        conn.execute("UPDATE athletes SET fair_value = ? WHERE id = ?", (fv, a["id"]))
        conn.execute("INSERT INTO fair_values VALUES (?,?,?) ON CONFLICT(day, athlete_id) DO UPDATE SET "
                     "fair_value = excluded.fair_value", (day, a["id"], fv))


def weeks_just_finished(conn):
    """Weeks whose every game is processed (or called off) and that haven't been re-checked yet."""
    rows = conn.execute("""
        SELECT week FROM games GROUP BY week
        HAVING SUM(CASE WHEN processed_at IS NULL AND status NOT IN (?, ?) THEN 1 ELSE 0 END) = 0
           AND SUM(CASE WHEN processed_at IS NOT NULL THEN 1 ELSE 0 END) > 0
           AND week NOT IN (SELECT week FROM group_checks)
        ORDER BY week""", SKIPPED).fetchall()
    return [r["week"] for r in rows]


def week_promise(promise_by_week, week):
    """A week's share of the season's promise (Live Rules sheet); 1 outside weeks 1-18 or with no promise row."""
    if promise_by_week and 1 <= week <= len(promise_by_week):
        return promise_by_week[week - 1]
    return 1.0


def run_recheck(conn, week, econ):
    so_far = season_so_far(conn, through_week=week, promise_by_week=econ["live"].get("promise_by_week"))
    results = []
    for g in conn.execute("SELECT * FROM groups ORDER BY name").fetchall():
        actual = promised = 0.0
        for a in conn.execute("SELECT id, prior_ptg FROM athletes WHERE grp = ?", (g["name"],)):
            _, pts, promised_games = so_far[a["id"]]
            actual += pts
            promised += a["prior_ptg"] * promised_games
        new, ratio = pricing.recheck(g["multiplier"], week, actual, promised, econ)
        conn.execute("UPDATE groups SET multiplier = ? WHERE name = ?", (new, g["name"]))
        conn.execute("INSERT INTO group_checks VALUES (?,?,?,?,?,?)", (week, g["name"], actual, promised, ratio, new))
        results.append({"week": week, "group": g["name"], "actual": actual, "promised": promised, "ratio": ratio,
                        "before": g["multiplier"], "after": new})
    return results


# ---- Report

def make_report(conn, day, now, payouts, before_fv, checks):
    names = {r["id"]: dict(r) for r in conn.execute("SELECT id, ticker, name, team, pos, fair_value FROM athletes")}
    top = sorted(payouts, key=lambda p: -p["per_share"])[:10]
    moves = []
    for aid, a in names.items():
        old = before_fv[aid]
        moves.append({"ticker": a["ticker"], "name": a["name"], "before": old, "after": a["fair_value"],
                      "change": a["fair_value"] / old - 1})
    moves.sort(key=lambda m: -m["change"])
    players = []
    for p in conn.execute("SELECT id, name FROM players"):
        earned = sum(c for (c,) in conn.execute(
            "SELECT d.cents FROM dividends d JOIN games g ON g.id = d.game_id WHERE g.day = ? AND d.player = ?",
            (day, p["id"])))
        pf = L.portfolio(conn, p["id"], now)
        players.append({"player": p["name"], "dividend_cents": earned, "net_worth_cents": pf["net_worth_cents"],
                        "cash_cents": pf["cash_cents"]})
    start, end = L.record_time(day), L.record_time(_next_day(day))
    busiest = [dict(r) for r in conn.execute(
        "SELECT a.ticker, a.name, SUM(ABS(t.shares)) AS shares, COUNT(*) AS trades FROM trades t "
        "JOIN athletes a ON a.id = t.athlete_id WHERE t.at >= ? AND t.at < ? GROUP BY a.id ORDER BY shares DESC LIMIT 5",
        (start, end))]
    return {
        "day": day, "made_at": L.utc_text(now),
        "games": sorted({p["game"] for p in payouts}),
        "top_dividends": [{**names[p["athlete_id"]], "points": p["points"], "per_share": p["per_share"],
                           "paid_cents": p["paid_cents"], "game": p["game"]} for p in top],
        "gainers": [m for m in moves if m["change"] > 0.0005][:5],
        "losers": [m for m in moves[::-1] if m["change"] < -0.0005][:5],
        "busiest": busiest, "players": players, "group_checks": checks,
    }


def _next_day(day):
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def report_text(r):
    """The market report as plain text for the terminal and reports/ folder."""
    out = [f"Market report for games on {r['day']}", ""]
    if r["games"]:
        out.append("Games: " + "; ".join(r["games"]))
    for p in r["players"]:
        out.append(f"{p['player']}: dividends today ${p['dividend_cents'] / 100:,.2f}, net worth "
                   f"${p['net_worth_cents'] / 100:,.2f} (cash ${p['cash_cents'] / 100:,.2f})")
    if r["top_dividends"]:
        out += ["", "Biggest dividends per share:"]
        for t in r["top_dividends"]:
            out.append(f"  {t['ticker']:6} {t['name']:24} {t['points']:6.2f} pts  ${t['per_share']:.4f}/share  ({t['game']})")
    out += ["", "Biggest price rises:"]
    out += [f"  {m['ticker']:6} {m['name']:24} ${m['before']:7.2f} -> ${m['after']:7.2f}  {m['change']:+.1%}"
            for m in r["gainers"]]
    out += ["", "Biggest price falls:"]
    out += [f"  {m['ticker']:6} {m['name']:24} ${m['before']:7.2f} -> ${m['after']:7.2f}  {m['change']:+.1%}"
            for m in r["losers"]]
    if r["busiest"]:
        out += ["", "Busiest stocks:"] + [f"  {b['ticker']:6} {b['shares']} shares in {b['trades']} trades"
                                          for b in r["busiest"]]
    if r["group_checks"]:
        out += ["", f"Weekly group re-check (after week {r['group_checks'][0]['week']}):"]
        for c in r["group_checks"]:
            ratio = "n/a" if c["ratio"] is None else f"{c['ratio']:.0%}"
            out.append(f"  {c['group']:10} paid {ratio} of promise; multiplier {c['before']:.3f} -> {c['after']:.3f}")
    return "\n".join(out)
