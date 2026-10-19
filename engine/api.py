"""What the screens ask for. Plain functions that take an open connection and a moment in time and return plain
dicts, so the tests can call them directly. They only read, except `place_trade`, which goes through the ledger.
The web page never works out a price or changes a balance itself."""
import json

from . import ledger as L
from . import market_maker as MM
from . import nightly as N

PLAYER = "you"


def _mm(conn):
    return L.economy(conn)["market_maker"]


def _two_latest_values(conn):
    """{athlete_id: (latest fair value, the one before)} from the nightly history."""
    days = [r[0] for r in conn.execute("SELECT DISTINCT day FROM fair_values ORDER BY day DESC LIMIT 2")]
    out = {}
    for i, day in enumerate(days):
        for r in conn.execute("SELECT athlete_id, fair_value FROM fair_values WHERE day = ?", (day,)):
            out.setdefault(r["athlete_id"], [None, None])[i] = r["fair_value"]
    return out


def status(conn, now):
    last = conn.execute("SELECT MAX(day) FROM reports").fetchone()[0]
    return {"season": L.meta(conn, "season"), "sport": L.meta(conn, "sport"), "now": L.utc_text(now),
            "last_update": last, "player": PLAYER}


def market(conn, now):
    mm = _mm(conn)
    held = {r[0]: r[1] for r in conn.execute("SELECT athlete_id, SUM(shares) FROM trades GROUP BY athlete_id")}
    mine = {r[0]: r[1] for r in conn.execute("SELECT athlete_id, SUM(shares) FROM trades WHERE player = ? "
                                              "GROUP BY athlete_id", (PLAYER,))}
    values = _two_latest_values(conn)
    last_pts = {}
    for r in conn.execute("SELECT s.athlete_id, s.points FROM stat_lines s JOIN games g ON g.id = s.game_id "
                          "ORDER BY g.kickoff"):
        last_pts[r["athlete_id"]] = r["points"]
    in_game = {r["team"] for r in conn.execute(
        "SELECT home AS team FROM games WHERE kickoff <= ? AND processed_at IS NULL AND status NOT IN "
        "('STATUS_POSTPONED','STATUS_CANCELED') UNION SELECT away FROM games WHERE kickoff <= ? AND processed_at IS "
        "NULL AND status NOT IN ('STATUS_POSTPONED','STATUS_CANCELED')", (L.utc_text(now), L.utc_text(now)))}
    nxt = {}
    for g in conn.execute("SELECT home, away, kickoff FROM games WHERE kickoff > ? ORDER BY kickoff", (L.utc_text(now),)):
        nxt.setdefault(g["home"], g["kickoff"])
        nxt.setdefault(g["away"], g["kickoff"])
    rows = []
    for a in conn.execute("SELECT * FROM athletes ORDER BY fair_value DESC"):
        sell, buy = MM.quote(a["fair_value"], held.get(a["id"], 0), a["step_shares"], mm)
        v = values.get(a["id"])
        change = (v[0] / v[1] - 1) if v and v[0] and v[1] else None
        rows.append({"ticker": a["ticker"], "name": a["name"], "team": a["team"], "pos": a["pos"],
                     "buy": buy, "sell": sell, "change": change, "last_points": last_pts.get(a["id"]),
                     "next_kickoff": nxt.get(a["team"]), "in_game": a["team"] in in_game,
                     "mine": mine.get(a["id"], 0)})
    return {"athletes": rows}


def athlete_page(conn, ticker, now):
    a = L.athlete(conn, ticker)
    mm = _mm(conn)
    held = L.market_held(conn, a["id"])
    sell, buy = MM.quote(a["fair_value"], held, a["step_shares"], mm)
    cash = L.cash_cents(conn, PLAYER)
    mine = L.shares_held(conn, PLAYER, a["id"])
    in_game = L.current_team_game(conn, a, now)
    nxt = L.next_game(conn, a["team"], now)
    log = []
    for r in conn.execute("""SELECT g.week, g.day, g.home, g.away, s.team, s.points, p.per_share,
                                    COALESCE(d.cents, 0) AS my_cents, COALESCE(d.shares, 0) AS my_shares
                             FROM stat_lines s JOIN games g ON g.id = s.game_id
                             JOIN payouts p ON p.game_id = s.game_id AND p.athlete_id = s.athlete_id
                             LEFT JOIN dividends d ON d.game_id = s.game_id AND d.athlete_id = s.athlete_id
                                  AND d.player = ?
                             WHERE s.athlete_id = ? ORDER BY g.kickoff DESC""", (PLAYER, a["id"])):
        opp = r["home"] if r["team"] == r["away"] else r["away"]
        log.append({"week": r["week"], "day": r["day"], "opponent": opp, "away": r["team"] == r["away"],
                    "points": r["points"], "per_share": r["per_share"], "my_cents": r["my_cents"],
                    "my_shares": r["my_shares"]})
    values = [dict(r) for r in conn.execute("SELECT day, fair_value FROM fair_values WHERE athlete_id = ? ORDER BY day",
                                            (a["id"],))]
    return {"ticker": a["ticker"], "name": a["name"], "team": a["team"], "pos": a["pos"], "fair_value": a["fair_value"],
            "buy": buy, "sell": sell, "start_price": a["start_price"], "mine": mine, "cash_cents": cash,
            "max_buy": 0 if in_game else MM.most_affordable(a["fair_value"], held, cash, a["step_shares"], mm),
            "in_game": bool(in_game),
            "in_game_note": f"{a['name']} is in a game. Trading reopens after the overnight update." if in_game else None,
            "next_kickoff": nxt["kickoff"] if nxt else None, "log": log, "values": values}


def quote(conn, ticker, side, shares, now):
    """A trade preview. A refused trade comes back as {"ok": False, "message": ...} for the page to show."""
    try:
        q = L.quote_trade(conn, PLAYER, ticker, side, shares, now)
    except L.TradeRefused as e:
        return {"ok": False, "message": str(e)}
    n = abs(q["shares"])
    return {"ok": True, "side": side, "shares": n, "total_cents": abs(q["cents"]), "expect_cents": q["cents"],
            "average": abs(q["cents"]) / n / 100, "price_after": q["price_after"], "ticker": q["athlete"]["ticker"]}


def place_trade(conn, ticker, side, shares, expect_cents, now):
    try:
        t = L.trade(conn, PLAYER, ticker, side, shares, now, expect_cents=expect_cents)
    except L.TradeRefused as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "ticker": t["ticker"], "shares": abs(t["shares"]), "side": side, "cents": abs(t["cents"])}


def portfolio(conn, now):
    pf = L.portfolio(conn, PLAYER, now)
    start = conn.execute("SELECT starting_cents FROM players WHERE id = ?", (PLAYER,)).fetchone()[0]
    pf["starting_cents"] = start
    pf["dividends_cents"] = conn.execute("SELECT COALESCE(SUM(cents), 0) FROM dividends WHERE player = ?",
                                         (PLAYER,)).fetchone()[0]
    pf["activity"] = L.activity(conn, PLAYER, 100)
    return pf


def latest_report(conn):
    row = conn.execute("SELECT body FROM reports ORDER BY day DESC LIMIT 1").fetchone()
    if not row:
        return {"report": None, "text": "No report yet. Run the nightly job."}
    report = json.loads(row["body"])
    return {"report": report, "text": N.report_text(report)}
