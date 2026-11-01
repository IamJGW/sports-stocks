"""The nightly robot online (engine/robot.py, db/migrations/005_robot.sql), on the Supabase TEST project with a fake
box-score feed. Skipped without the test project's keys.

A pretend season 'zz-robot' (real levers, three athletes) gets fresh pretend games each run, since stat lines and
payouts are final. A pretend day: who held at midnight is paid and later buyers aren't, an order waiting through a
game fills overnight and is in the morning report, a league past its end date stops being paid and is closed, the
self-check passes, the status row is written, and running again changes nothing. The database refuses dividends
that don't match its own count of the holdings."""
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from openpyxl import load_workbook

import online
from helpers import ECON, FakeFeed
from engine import ledger as L, nightly as N, pricing, robot
from engine.online import OnlineError
from tools import hand_check

SEASON = "zz-robot"
RATE = 0.1
PRIOR = 14.0
FV = pricing.fair_value(pricing.expected_ptg(PRIOR, 1.0, 0, 0, ECON), RATE, ECON, "NFL")
A, B, C = "RA1", "RB1", "RC1"  # ESPN-style ids; online ids are 'zz-robot:RA1'
TEAM = {A: "RAA", B: "RBB", C: "RCC"}
WEIGHTS = ECON["sports"]["NFL"]["scoring"]
ONLINE = lambda espn: f"{SEASON}:{espn}"  # noqa: E731


def ensure_season(p):
    p.insert("seasons", [{"id": SEASON, "sport": "NFL", "season": 2026, "rate": RATE, "economy": ECON}],
             on_conflict="id", existing="ignore")
    p.insert("groups", [{"season_id": SEASON, "name": g, "multiplier": 1.0} for g in pricing.sport_groups(ECON, "NFL")],
             on_conflict="season_id,name", existing="ignore")
    p.insert("athletes", [{"id": ONLINE(a), "season_id": SEASON, "espn_id": a, "ticker": a, "name": f"Robot {a}",
                           "team": t, "pos": "RB", "grp": "NFL RB", "prior_ppg": PRIOR, "prior_ptg": PRIOR,
                           "start_price": FV, "step_shares": ECON["market_maker"]["dollars_per_step"] / FV,
                           "fair_value": FV} for a, t in TEAM.items()], on_conflict="id", existing="ignore")
    # A game left unprocessed by an earlier run that stopped would hold back every day after it.
    p.update("games", {"status": "STATUS_CANCELED"}, season_id=f"eq.{SEASON}", processed_at="is.null")


def eastern_today():
    return datetime.now(timezone.utc).astimezone(L.EASTERN).date()


def at_4am(d):
    return datetime(d.year, d.month, d.day, 4, tzinfo=L.EASTERN).astimezone(timezone.utc)


class Robot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = online.project()[0]
        cls.ph = online.phones(3)
        ensure_season(cls.p)
        cls.run_id = str(int(time.time()))
        cls.week = 100 + int(cls.run_id) % 1_000_000  # its own week, so fair values stay put run after run

    def setUp(self):
        self.p.update("games", {"status": "STATUS_CANCELED"}, season_id=f"eq.{SEASON}", processed_at="is.null")
        self.feed = FakeFeed()
        self.today = eastern_today()

    # ---- helpers

    def league(self, phones, ends):
        got = phones[0].rpc("create_league", p_name="Robot test", p_season=SEASON,
                            p_starts_on=self.today.isoformat(), p_ends_on=ends.isoformat(), p_display_name="R1")
        for ph in phones[1:]:
            ph.rpc("join_league", p_code=got["join_code"], p_display_name=f"R{ph.n}")
        return got["market_id"]

    def order(self, ph, m, a, side, kind, shares, limit=None):
        if kind == "market":
            limit = ph.rpc("place_order", p_market=m, p_athlete=ONLINE(a), p_side=side, p_kind=kind,
                           p_shares=shares, p_preview=True)["worst_cents"]
        return ph.rpc("place_order", p_market=m, p_athlete=ONLINE(a), p_side=side, p_kind=kind, p_shares=shares,
                      p_limit_cents=limit)

    def game(self, name, kickoff, athlete, stats):
        gid = f"{name}{self.run_id}"
        self.feed.add_game(gid, self.week, kickoff, TEAM[athlete], "RZZ", {athlete: (TEAM[athlete], stats)})
        return gid

    def sync(self):
        conn, _ = robot.mirror(self.p, SEASON)
        N.sync_schedule(conn, self.feed, weeks=[self.week])
        robot.push_schedule(self.p, SEASON, conn)

    def run_robot(self, day):
        out = []
        code = robot.run(self.p, SEASON, self.feed, at_4am(day), quiet=True, log=out.append, weeks=[self.week])
        return code, "\n".join(out)

    def dividends(self, gid):
        return self.p.select("dividends", game_id=f"eq.{ONLINE(gid)}")

    # ---- tests

    def test_a_pretend_day(self):
        t, t1, t2 = self.today, self.today + timedelta(days=1), self.today + timedelta(days=2)
        p1, p2, p3 = self.ph
        l1 = self.league([p1, p2], ends=t1)
        l2 = self.league([p3], ends=t)  # ends today: paid for today's games, not tomorrow's, then closed
        self.order(p1, l1, A, "buy", "market", 100)
        self.order(p1, l1, B, "buy", "market", 100)
        self.order(p3, l2, B, "buy", "market", 40)
        waiting = self.order(p3, l2, C, "buy", "limit", 10, 100)

        # Today's game for A kicks off now (bought after midnight: no dividend); tomorrow's for B (held at midnight).
        kick = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=30)
        if L.eastern_day(kick) != t.isoformat():
            self.skipTest("Too close to midnight Eastern.")
        ga = self.game("ga", kick, A, {"rush_yd": 80, "rush_td": 1})
        b_stats = {"rec": 5, "rec_yd": 60, "rec_td": 1}
        b_pts = round(pricing.score({**{k: 0 for k in WEIGHTS}, **b_stats}, WEIGHTS), 2)
        gb = self.game("gb", datetime(t1.year, t1.month, t1.day, 13, tzinfo=L.EASTERN), B, b_stats)
        self.sync()

        # During A's game the market maker is out: a buy placed now waits, and fills overnight when he's back.
        buy = self.order(p2, l1, A, "buy", "limit", 50, 100_000)  # $1,000: above any price he'll ask
        self.assertEqual(self.p.select("orders", id=f"eq.{buy['order_id']}")[0]["status"], "open")

        code, out = self.run_robot(t2)
        self.assertEqual(code, 0, out)
        self.assertIn(f"{t.isoformat()}: 1 games", out)
        self.assertIn(f"{t1.isoformat()}: 1 games", out)

        self.assertEqual(self.dividends(ga), [])  # nobody held A at today's midnight
        gb_paid = {(d["market_id"], d["shares"]): d["cents"] for d in self.dividends(gb) if d["market_id"] in (l1, l2)}
        self.assertEqual(gb_paid, {(l1, 100): N.dividend_cents(100, b_pts, RATE, 1.0)})  # not l2: it ended today
        self.assertAlmostEqual(self.p.select("payouts", game_id=f"eq.{ONLINE(gb)}")[0]["per_share"], b_pts * RATE, 12)

        self.assertEqual(self.p.select("orders", id=f"eq.{buy['order_id']}")[0]["status"], "filled")
        report = self.p.select("reports", market_id=f"eq.{l1}", day=f"eq.{t.isoformat()}")[0]["body"]
        self.assertEqual([f["order_id"] for f in report["overnight_fills"]], [buy["order_id"]])
        self.assertEqual({r["display_name"] for r in report["players"]}, {"R1", "R2"})
        self.assertEqual(len(self.p.select("reports", market_id=f"eq.{l1}")), 2)
        self.assertEqual([r["day"] for r in self.p.select("reports", market_id=f"eq.{l2}")], [t.isoformat()])

        for m in (l1, l2):
            self.assertIsNotNone(self.p.select("markets", id=f"eq.{m}")[0]["closed_at"])
            self.assertEqual(self.p.rpc("check_league", p_market=m), [])
        w = self.p.select("orders", id=f"eq.{waiting['order_id']}")[0]
        self.assertEqual((w["status"], w["close_reason"]), ("cancelled", "league over"))

        status = self.p.select("robot_status", season_id=f"eq.{SEASON}")[0]
        self.assertGreaterEqual(status["last_day"], t1.isoformat())
        self.assertIsNone(status["stop_reason"])
        self.assertIsNotNone(status["last_ok_at"])

        # Running again changes nothing.
        code, out = self.run_robot(t2)
        self.assertEqual(code, 0, out)
        self.assertIn("Nothing new to process", out)
        self.assertEqual({(d["market_id"], d["shares"]): d["cents"] for d in self.dividends(gb)
                          if d["market_id"] in (l1, l2)}, gb_paid)

    def test_b_database_recounts_dividends(self):
        t1 = self.today + timedelta(days=1)
        p1 = self.ph[0]
        m = self.league([p1], ends=t1)
        self.order(p1, m, C, "buy", "market", 10)
        gc = self.game("gc", datetime(t1.year, t1.month, t1.day, 13, tzinfo=L.EASTERN), C, {"rush_yd": 100})
        self.sync()
        conn, _ = robot.mirror(self.p, SEASON)
        day = t1.isoformat()
        parsed = N.fetch_day(conn, day, self.feed)
        rows = robot.day_rows(self.p, SEASON, conn, day, parsed, N.process_day(conn, day, parsed, at_4am(t1)))
        others = [d for d in rows["dividends"] if d["market_id"] != m]  # earlier runs' leagues, still open tomorrow
        good = [d for d in rows["dividends"] if d["market_id"] == m]
        self.assertEqual([(d["market_id"], d["shares"]) for d in good], [(m, 10)])

        def refused(pattern, dividends):
            with self.assertRaisesRegex(OnlineError, pattern):
                self.p.rpc("robot_day", p_season=SEASON, p_day=day, p={**rows, "dividends": dividends})

        refused("sent 11 shares, held 10", others + [{**good[0], "shares": 11}])
        refused("holder not paid", others)
        refused("not a holder", rows["dividends"] + [{**good[0], "member_id": self.ph[1].user_id}])
        refused("sent .* cents", others + [{**good[0], "cents": good[0]["cents"] + 1}])
        # Nothing went in.
        self.assertEqual(self.p.select("stat_lines", game_id=f"eq.{ONLINE(gc)}"), [])
        self.assertIsNone(self.p.select("games", id=f"eq.{ONLINE(gc)}")[0]["processed_at"])

        got = self.p.rpc("robot_day", p_season=SEASON, p_day=day, p=rows)
        self.assertEqual(got["dividends"], len(rows["dividends"]))
        self.assertEqual(robot.read_back(self.p, rows), [])
        self.assertTrue(self.p.rpc("robot_day", p_season=SEASON, p_day=day, p=rows)["skipped"])
        self.assertEqual(len(self.dividends(gc)), len(rows["dividends"]))

    def test_c_bad_box_score_stops_and_says_why(self):
        t1 = self.today + timedelta(days=1)
        self.game("gd", datetime(t1.year, t1.month, t1.day, 13, tzinfo=L.EASTERN), A, {"rush_yd": 10})
        self.feed.boxes[f"gd{self.run_id}"]["problems"].append("player stats are empty")
        code, out = self.run_robot(t1 + timedelta(days=1))
        self.assertEqual(code, 1, out)
        status = self.p.select("robot_status", season_id=f"eq.{SEASON}")[0]
        self.assertEqual(status["stopped_on"], t1.isoformat())
        self.assertIn("player stats are empty", status["stop_reason"])
        # Set aside, the day pays without it (here: nothing else that day) and the run is clean again.
        self.p.rpc("robot_set_aside", p_game=ONLINE(f"gd{self.run_id}"), p_reason="test")
        code, out = self.run_robot(t1 + timedelta(days=1))
        self.assertEqual(code, 0, out)
        self.assertIn("set-aside", out)
        self.assertIsNone(self.p.select("robot_status", season_id=f"eq.{SEASON}")[0]["stop_reason"])

    def test_d_hand_check_reads_the_database(self):
        t2 = self.today + timedelta(days=2)
        p1, p2 = self.ph[:2]
        m = self.league([p1, p2], ends=t2 + timedelta(days=1))
        # A, whose earlier games here were either before today's trades or set aside: holdings only count from now.
        self.order(p1, m, A, "buy", "market", 100)
        book = p1.rpc("order_book", p_market=m, p_athlete=ONLINE(A))["market_maker"]
        price = (book["sells_from_cents"] + book["buys_from_cents"]) // 2
        self.order(p1, m, A, "sell", "limit", 30, price)
        self.order(p2, m, A, "buy", "market", 30)  # player to player, so the seller's holding falls too
        stats = {"rush_yd": 90, "rush_td": 1}
        gid = self.game("ge", datetime(t2.year, t2.month, t2.day, 13, tzinfo=L.EASTERN), A, stats)
        self.sync()
        code, out = self.run_robot(t2 + timedelta(days=1))
        self.assertEqual(code, 0, out)
        paid = {d["member_id"]: d for d in self.dividends(gid) if d["market_id"] == m}
        members = {r["display_name"]: r["id"] for r in self.p.select("members", market_id=f"eq.{m}")}
        self.assertEqual(sorted(d["shares"] for d in paid.values()), [30, 70])

        with tempfile.TemporaryDirectory() as out_dir:
            for name, member in members.items():
                conn = hand_check.online_save(self.p, SEASON, m, member)
                path = hand_check.write_week(conn, self.week, out_dir)
                self.assertTrue(hand_check.recalculate(path))
                lines, bad = hand_check.results(path)
                self.assertGreater(lines, 0)
                self.assertEqual(bad, 0, name)
                wb = load_workbook(path, data_only=True)["Check"]
                self.assertAlmostEqual(wb["C4"].value, paid[member]["cents"] / 100, 2)
                self.assertAlmostEqual(wb["C5"].value, paid[member]["cents"] / 100, 2)

            # A wrong amount in the data must show as a mismatch, or the checks above prove nothing.
            conn = hand_check.online_save(self.p, SEASON, m, members["R1"])
            conn.execute("DROP TRIGGER dividends_are_final_u")
            conn.execute("UPDATE dividends SET cents = cents + 1 WHERE game_id = ?", (gid,))
            path = hand_check.write_week(conn, self.week, out_dir)
            self.assertTrue(hand_check.recalculate(path))
            self.assertEqual(hand_check.results(path)[1], 1)


if __name__ == "__main__":
    unittest.main()
