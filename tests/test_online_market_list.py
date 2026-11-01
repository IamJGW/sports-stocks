"""The market list (db/migrations/006_market_list.sql): last trade, best bid and best offer for every athlete in one
call, agreeing with order_book, on the Supabase TEST project. Skipped without its keys."""
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

import online
from engine import ledger as L
from engine.online import OnlineError

A, B, C = online.athlete_id("AAA"), online.athlete_id("BBB"), online.athlete_id("CCC")


def today():
    return datetime.now(timezone.utc).astimezone(L.EASTERN).date()


class MarketList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.robot = online.project()[0]
        online.ensure_season()
        online.reset_season()
        cls.p1, cls.p2, cls.p3 = online.phones(3)

    def tearDown(self):
        online.reset_season()

    def league(self, season=online.SEASON):
        got = self.p1.rpc("create_league", p_name="List test", p_season=season, p_starts_on=today().isoformat(),
                          p_ends_on=(today() + timedelta(days=7)).isoformat(), p_display_name="L1")
        self.p2.rpc("join_league", p_code=got["join_code"], p_display_name="L2")
        return got["market_id"]

    def order(self, ph, m, a, side, kind, shares, limit=None):
        if kind == "market":
            limit = ph.rpc("place_order", p_market=m, p_athlete=a, p_side=side, p_kind=kind, p_shares=shares,
                           p_preview=True)["worst_cents"]
        return ph.rpc("place_order", p_market=m, p_athlete=a, p_side=side, p_kind=kind, p_shares=shares,
                      p_limit_cents=limit)

    def row(self, m, a):
        return next(r for r in self.p1.rpc("market_list", p_market=m) if r["athlete_id"] == a)

    def agrees(self, m, a):
        """The list's row is what order_book says, with sleeping orders and an absent market maker left out."""
        b, r = self.p1.rpc("order_book", p_market=m, p_athlete=a), self.row(m, a)
        mm = b["market_maker"]
        bids = [l["price"] for l in b["bids"] if l["shares"] > l["asleep"]]
        asks = [l["price"] for l in b["asks"] if l["shares"] > l["asleep"]]
        if not mm["out"]:
            bids += [mm["buys_from_cents"]] if mm["buys_from_cents"] is not None else []
            asks += [mm["sells_from_cents"]]
        self.assertEqual(r["best_bid_cents"], max(bids) if bids else None)
        self.assertEqual(r["best_ask_cents"], min(asks) if asks else None)
        self.assertEqual(r["last_cents"], b["last"]["price_cents"] if b["last"] else None)
        self.assertEqual(r["mm_out"], mm["out"])
        return r

    def test_no_trades_yet(self):
        m = self.league()
        r = self.agrees(m, A)
        self.assertIsNone(r["last_cents"])
        self.assertIsNone(r["best_bid_cents"])  # he holds none, so nothing to buy back
        self.assertIsNotNone(r["best_ask_cents"])

    def test_every_athlete_of_the_league_once(self):
        m = self.league()
        rows = self.p1.rpc("market_list", p_market=m)
        want = {a["id"] for a in self.robot.select("athletes", season_id=f"eq.{online.SEASON}")}
        self.assertEqual(sorted(r["athlete_id"] for r in rows), sorted(want))

    def test_players_better_than_the_market_maker(self):
        m = self.league()
        self.order(self.p1, m, A, "buy", "market", 100)
        before = self.row(m, A)
        self.order(self.p2, m, A, "buy", "limit", 5, before["best_bid_cents"] + 3)
        self.order(self.p1, m, A, "sell", "limit", 5, before["best_ask_cents"] - 3)
        r = self.agrees(m, A)
        self.assertEqual(r["best_bid_cents"], before["best_bid_cents"] + 3)
        self.assertEqual(r["best_ask_cents"], before["best_ask_cents"] - 3)

    def test_last_trade_is_each_shares_price(self):
        m = self.league()
        self.order(self.p1, m, B, "buy", "market", 40)
        r = self.agrees(m, B)
        got = self.robot.select("trades", market_id=f"eq.{m}", athlete_id=f"eq.{B}")[0]
        self.assertEqual(r["last_cents"], round(got["cents"] / got["shares"]))

    def test_market_maker_out_and_a_sleeping_order(self):
        m = self.league()
        self.order(self.p1, m, C, "buy", "market", 10)
        self.order(self.p2, m, C, "buy", "limit", 5, 4000)   # placed before kickoff: sleeps through the game
        online.kick_off("CCC")
        r = self.agrees(m, C)
        self.assertTrue(r["mm_out"])
        self.assertIsNone(r["best_bid_cents"])
        self.assertIsNone(r["best_ask_cents"])
        online.process("CCC")
        r = self.agrees(m, C)
        self.assertFalse(r["mm_out"])
        self.assertGreater(r["best_bid_cents"], 4000)

    def test_only_members_may_ask(self):
        m = self.league()
        with self.assertRaises(OnlineError):
            self.p3.rpc("market_list", p_market=m)
        with self.assertRaises(OnlineError):
            online.anonymous().rpc("market_list", p_market=m)

    def test_it_changes_nothing(self):
        m = self.league()
        self.order(self.p1, m, A, "buy", "market", 10)
        self.order(self.p2, m, A, "buy", "limit", 3, 100)
        snap = lambda: (self.robot.select("orders", market_id=f"eq.{m}", order="id"),   # noqa: E731
                        self.robot.select("trades", market_id=f"eq.{m}", order="id"))
        before = snap()
        self.p1.rpc("market_list", p_market=m)
        self.assertEqual(snap(), before)
        self.assertEqual(self.robot.rpc("check_league", p_market=m), [])

    def test_quick_for_the_whole_nfl_list(self):
        m = self.league("nfl-2026")
        t0 = time.time()
        rows = self.p1.rpc("market_list", p_market=m)
        took = time.time() - t0
        self.assertEqual(len(rows), 120)
        self.assertLess(took, 2.0)


class Migration(unittest.TestCase):
    def test_test_project_has_every_file_and_passes_the_safety_check(self):
        online.project()
        r = subprocess.run([sys.executable, "tools/db.py", "test", "status"], cwd=online.ROOT, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("WAITING", r.stdout)
        self.assertIn("done     006_market_list.sql", r.stdout)
        self.assertIn("Safety check passed", r.stdout)


if __name__ == "__main__":
    unittest.main()
