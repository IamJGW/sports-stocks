"""The game's books: one SQLite file. Only this module and nightly.py write to it.

Trades and dividends are rows that are never edited or deleted. Cash and holdings are always added up from them, so
there is no running balance that could drift. Money is whole cents. All times are stored in UTC as
'YYYY-MM-DDTHH:MM:SSZ', so comparing the strings compares the times.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import market_maker as MM
from . import pricing

EASTERN = ZoneInfo("America/New_York")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, name TEXT NOT NULL, starting_cents INTEGER NOT NULL,
    joined_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS athletes (id TEXT PRIMARY KEY, ticker TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
    team TEXT NOT NULL, pos TEXT NOT NULL, grp TEXT NOT NULL, prior_ppg REAL NOT NULL, prior_ptg REAL NOT NULL,
    start_price REAL NOT NULL, step_shares REAL NOT NULL, fair_value REAL NOT NULL);
CREATE TABLE IF NOT EXISTS groups (name TEXT PRIMARY KEY, multiplier REAL NOT NULL);
CREATE TABLE IF NOT EXISTS group_checks (week INTEGER NOT NULL, grp TEXT NOT NULL, actual REAL, promised REAL,
    ratio REAL, multiplier REAL NOT NULL, PRIMARY KEY (week, grp));
CREATE TABLE IF NOT EXISTS games (id TEXT PRIMARY KEY, week INTEGER NOT NULL, kickoff TEXT NOT NULL,
    day TEXT NOT NULL, home TEXT NOT NULL, away TEXT NOT NULL, playoff INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL, processed_at TEXT);
CREATE TABLE IF NOT EXISTS stat_lines (game_id TEXT NOT NULL, athlete_id TEXT NOT NULL, team TEXT NOT NULL,
    stats TEXT NOT NULL, points REAL NOT NULL, PRIMARY KEY (game_id, athlete_id));
CREATE TABLE IF NOT EXISTS payouts (game_id TEXT NOT NULL, athlete_id TEXT NOT NULL, points REAL NOT NULL,
    boost REAL NOT NULL, per_share REAL NOT NULL, record_time TEXT NOT NULL, paid_at TEXT NOT NULL,
    PRIMARY KEY (game_id, athlete_id));
CREATE TABLE IF NOT EXISTS dividends (game_id TEXT NOT NULL, athlete_id TEXT NOT NULL, player TEXT NOT NULL,
    shares INTEGER NOT NULL, cents INTEGER NOT NULL, PRIMARY KEY (game_id, athlete_id, player));
CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, player TEXT NOT NULL,
    athlete_id TEXT NOT NULL, shares INTEGER NOT NULL, cents INTEGER NOT NULL, fair_value REAL NOT NULL,
    market_held_before INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS fair_values (day TEXT NOT NULL, athlete_id TEXT NOT NULL, fair_value REAL NOT NULL,
    PRIMARY KEY (day, athlete_id));
CREATE TABLE IF NOT EXISTS reports (day TEXT PRIMARY KEY, made_at TEXT NOT NULL, body TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS trades_are_final_u BEFORE UPDATE ON trades BEGIN SELECT RAISE(ABORT, 'trades are final'); END;
CREATE TRIGGER IF NOT EXISTS trades_are_final_d BEFORE DELETE ON trades BEGIN SELECT RAISE(ABORT, 'trades are final'); END;
CREATE TRIGGER IF NOT EXISTS dividends_are_final_u BEFORE UPDATE ON dividends BEGIN SELECT RAISE(ABORT, 'dividends are final'); END;
CREATE TRIGGER IF NOT EXISTS dividends_are_final_d BEFORE DELETE ON dividends BEGIN SELECT RAISE(ABORT, 'dividends are final'); END;
"""


class TradeRefused(Exception):
    """A trade the rules don't allow. The message is shown to the player as is."""


# ---- Time

def utc_text(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(text):
    text = text.replace("Z", "")
    fmt = "%Y-%m-%dT%H:%M:%S" if text.count(":") == 2 else "%Y-%m-%dT%H:%M"
    return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)


def eastern_day(dt):
    """The Eastern calendar date (YYYY-MM-DD) a moment falls on."""
    return dt.astimezone(EASTERN).date().isoformat()


def record_time(day):
    """Midnight Eastern at the start of an Eastern date, in UTC text: who held shares then is paid for that day."""
    y, m, d = map(int, day.split("-"))
    return utc_text(datetime(y, m, d, tzinfo=EASTERN))


# ---- Setup

def connect(path):
    conn = sqlite3.connect(path, isolation_level=None)  # we manage transactions ourselves
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value)))


def create_game(conn, econ, prior_rows, sport, season, player_id, player_name, now):
    """A new market: list the athletes from last season, set starting prices, give the player starting cash."""
    if meta(conn, "season"):
        raise RuntimeError("This save already has a market in it.")
    book = pricing.starting_book(prior_rows, econ, sport)
    tickers = pricing.make_tickers(book["athletes"])
    step_dollars = econ["market_maker"]["dollars_per_step"]
    conn.execute("BEGIN")
    set_meta(conn, "season", season)
    set_meta(conn, "sport", sport)
    set_meta(conn, "rate", book["rate"])
    set_meta(conn, "economy", econ)
    set_meta(conn, "created_at", utc_text(now))
    for a in book["athletes"]:
        conn.execute("INSERT INTO athletes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (a["id"], tickers[a["id"]], a["name"], a["team"], a["pos"], a["group"], a["ppg"],
                      a["prior_ptg"], a["price"], step_dollars / a["price"], a["price"]))
    for g in pricing.sport_groups(econ, sport):
        conn.execute("INSERT INTO groups VALUES (?, 1.0)", (g,))
    conn.execute("INSERT INTO players VALUES (?,?,?,?)",
                 (player_id, player_name, round(econ["starting_cash"] * 100), utc_text(now)))
    conn.execute("COMMIT")


def economy(conn):
    return meta(conn, "economy")


# ---- Reading the books

def athlete(conn, key):
    """By id or ticker."""
    row = conn.execute("SELECT * FROM athletes WHERE id = ? OR ticker = ?", (key, str(key).upper())).fetchone()
    if not row:
        raise TradeRefused(f"No listed athlete '{key}'.")
    return row


def cash_cents(conn, player):
    traded = conn.execute("SELECT COALESCE(SUM(cents), 0) FROM trades WHERE player = ?", (player,)).fetchone()[0]
    paid = conn.execute("SELECT COALESCE(SUM(cents), 0) FROM dividends WHERE player = ?", (player,)).fetchone()[0]
    start = conn.execute("SELECT starting_cents FROM players WHERE id = ?", (player,)).fetchone()[0]
    return start + traded + paid


def shares_held(conn, player, athlete_id, before=None):
    q = "SELECT COALESCE(SUM(shares), 0) FROM trades WHERE player = ? AND athlete_id = ?"
    args = [player, athlete_id]
    if before:
        q += " AND at < ?"
        args.append(before)
    return conn.execute(q, args).fetchone()[0]


def market_held(conn, athlete_id):
    """Shares of this athlete held by all players together (what the market maker has sold, net)."""
    return conn.execute("SELECT COALESCE(SUM(shares), 0) FROM trades WHERE athlete_id = ?", (athlete_id,)).fetchone()[0]


def holders_at(conn, athlete_id, when):
    """{player: shares} held at a moment (for record time)."""
    rows = conn.execute("SELECT player, SUM(shares) AS n FROM trades WHERE athlete_id = ? AND at < ? GROUP BY player",
                        (athlete_id, when)).fetchall()
    return {r["player"]: r["n"] for r in rows if r["n"] > 0}


def current_team_game(conn, athlete_row, now):
    """The game that has the market maker stepped out of this athlete right now, if any: his team's game has kicked
    off but the overnight update hasn't processed it yet."""
    team = athlete_row["team"]
    return conn.execute("SELECT * FROM games WHERE (home = ? OR away = ?) AND kickoff <= ? AND processed_at IS NULL "
                        "AND status != 'STATUS_POSTPONED' AND status != 'STATUS_CANCELED' ORDER BY kickoff LIMIT 1",
                        (team, team, utc_text(now))).fetchone()


def next_game(conn, team, now):
    return conn.execute("SELECT * FROM games WHERE (home = ? OR away = ?) AND kickoff > ? ORDER BY kickoff LIMIT 1",
                        (team, team, utc_text(now))).fetchone()


# ---- Trading

def quote_trade(conn, player, key, side, shares, now):
    """What a trade would cost or bring in, without making it. Raises TradeRefused if it isn't allowed."""
    a = athlete(conn, key)
    mm = economy(conn)["market_maker"]
    if not isinstance(shares, int) or shares <= 0:
        raise TradeRefused("Choose a whole number of shares, at least 1.")
    if current_team_game(conn, a, now):
        raise TradeRefused(f"{a['name']} is in a game. The market maker reopens him after the overnight update.")
    held = market_held(conn, a["id"])
    if side == "buy":
        cents = MM.buy_cost_cents(a["fair_value"], held, shares, a["step_shares"], mm)
        if cents > cash_cents(conn, player):
            raise TradeRefused(f"Not enough cash: {shares} {a['ticker']} costs ${cents / 100:,.2f}.")
        after = MM.mid(a["fair_value"], held + shares, a["step_shares"], mm)
        return {"athlete": a, "side": side, "shares": shares, "cents": -cents, "held": held, "price_after": after}
    if side == "sell":
        mine = shares_held(conn, player, a["id"])
        if shares > mine:
            raise TradeRefused(f"You hold {mine} {a['ticker']}, so you can't sell {shares}.")
        cents = MM.sell_proceeds_cents(a["fair_value"], held, shares, a["step_shares"], mm)
        after = MM.mid(a["fair_value"], held - shares, a["step_shares"], mm)
        return {"athlete": a, "side": side, "shares": -shares, "cents": cents, "held": held, "price_after": after}
    raise TradeRefused("Side must be 'buy' or 'sell'.")


def trade(conn, player, key, side, shares, now, expect_cents=None):
    """Make a trade with the market maker. expect_cents is the total the player saw in the preview (negative for a
    buy); if the price has moved against them since, the trade is refused rather than filled at a surprise price."""
    conn.execute("BEGIN IMMEDIATE")  # nobody else can trade between the checks and the insert
    try:
        q = quote_trade(conn, player, key, side, shares, now)
        if expect_cents is not None and q["cents"] < expect_cents:
            raise TradeRefused("The price moved since your preview. Check the new price and try again.")
        cur = conn.execute("INSERT INTO trades (at, player, athlete_id, shares, cents, fair_value, market_held_before) "
                           "VALUES (?,?,?,?,?,?,?)", (utc_text(now), player, q["athlete"]["id"], q["shares"],
                                                      q["cents"], q["athlete"]["fair_value"], q["held"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"id": cur.lastrowid, **{k: v for k, v in q.items() if k != "athlete"}, "ticker": q["athlete"]["ticker"]}


# ---- Portfolio

def portfolio(conn, player, now):
    """Cash, holdings and net worth. Each holding is valued at what selling all of it to the market maker would bring
    in right now (walking the price down), so pumping a price never shows a paper gain."""
    mm = economy(conn)["market_maker"]
    rows = conn.execute("""
        SELECT a.*, SUM(t.shares) AS shares, SUM(CASE WHEN t.shares > 0 THEN -t.cents ELSE 0 END) AS bought_cents,
               SUM(CASE WHEN t.shares > 0 THEN t.shares ELSE 0 END) AS bought_shares
        FROM trades t JOIN athletes a ON a.id = t.athlete_id WHERE t.player = ? GROUP BY a.id""", (player,)).fetchall()
    holdings, value = [], 0
    for r in rows:
        if r["shares"] <= 0:
            continue
        held = market_held(conn, r["id"])
        liq = MM.sell_proceeds_cents(r["fair_value"], held, r["shares"], r["step_shares"], mm)
        divs = conn.execute("SELECT COALESCE(SUM(cents), 0) FROM dividends WHERE player = ? AND athlete_id = ?",
                            (player, r["id"])).fetchone()[0]
        holdings.append({"id": r["id"], "ticker": r["ticker"], "name": r["name"], "team": r["team"], "pos": r["pos"],
                         "shares": r["shares"], "avg_cost": r["bought_cents"] / r["bought_shares"] / 100,
                         "value_cents": liq, "dividend_cents": divs,
                         "in_game": bool(current_team_game(conn, r, now))})
        value += liq
    cash = cash_cents(conn, player)
    holdings.sort(key=lambda h: -h["value_cents"])
    return {"player": player, "cash_cents": cash, "holdings_cents": value, "net_worth_cents": cash + value,
            "holdings": holdings}


def activity(conn, player, limit=100):
    rows = conn.execute("""
        SELECT 'trade' AS kind, t.at AS at, a.ticker, a.name, t.shares, t.cents, NULL AS points, NULL AS game_id
          FROM trades t JOIN athletes a ON a.id = t.athlete_id WHERE t.player = ?
        UNION ALL
        SELECT 'dividend', p.paid_at, a.ticker, a.name, d.shares, d.cents, p.points, d.game_id
          FROM dividends d JOIN payouts p ON p.game_id = d.game_id AND p.athlete_id = d.athlete_id
          JOIN athletes a ON a.id = d.athlete_id WHERE d.player = ?
        ORDER BY at DESC LIMIT ?""", (player, player, limit)).fetchall()
    return [dict(r) for r in rows]
