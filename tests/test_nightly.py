import unittest

from helpers import ECON, FakeFeed, eastern, new_market
from engine import ledger as L, nightly as N


class Nightly(unittest.TestCase):
    def setUp(self):
        self.c = new_market()
        rows = self.c.execute("SELECT * FROM athletes ORDER BY start_price DESC").fetchall()
        self.a = rows[0]
        self.b = next(r for r in rows if r["team"] != self.a["team"])
        self.rate = L.meta(self.c, "rate")
        self.feed = FakeFeed()
        # Sunday 13 Sept 2026, 1 p.m. Eastern: a's team at home to b's team.
        self.feed.add_game("g1", 1, eastern(2026, 9, 13, 13), self.a["team"], self.b["team"], {
            self.a["id"]: (self.a["team"], {"rush_yd": 100, "rush_td": 2, "rec": 3, "rec_yd": 25}),  # 26.0 pts
            self.b["id"]: (self.b["team"], {"int": 3, "fum_lost": 1}),                               # -8 pts
        })

    def run_night(self, y, m, d):
        now = eastern(y, m, d, 4)
        N.sync_schedule(self.c, self.feed, weeks=[1])
        out = []
        for day in N.days_to_process(self.c, L.eastern_day(now)):
            out.append(N.process_day(self.c, day, N.fetch_day(self.c, day, self.feed), now))
        return out

    def test_holders_at_midnight_are_paid_and_later_buyers_are_not(self):
        L.trade(self.c, "you", self.a["ticker"], "buy", 100, eastern(2026, 9, 12, 23, 59))   # Saturday night
        L.trade(self.c, "you", self.a["ticker"], "buy", 50, eastern(2026, 9, 13, 0, 1))       # Sunday 12:01 a.m.
        self.run_night(2026, 9, 14)
        d = self.c.execute("SELECT * FROM dividends").fetchone()
        self.assertEqual(d["shares"], 100)
        self.assertEqual(d["cents"], round(100 * 26.0 * self.rate * 100))
        self.assertEqual(L.cash_cents(self.c, "you"),
                         100_000_00 + sum(r["cents"] for r in self.c.execute("SELECT cents FROM trades")) + d["cents"])

    def test_bad_game_pays_zero_never_charges(self):
        L.trade(self.c, "you", self.b["ticker"], "buy", 100, eastern(2026, 9, 10))
        self.run_night(2026, 9, 14)
        p = self.c.execute("SELECT * FROM payouts WHERE athlete_id = ?", (self.b["id"],)).fetchone()
        self.assertEqual(p["points"], -8.0)
        self.assertEqual(p["per_share"], 0.0)
        self.assertEqual(self.c.execute("SELECT cents FROM dividends").fetchone()["cents"], 0)

    def test_paid_once_even_if_run_again(self):
        L.trade(self.c, "you", self.a["ticker"], "buy", 100, eastern(2026, 9, 10))
        self.assertEqual(len(self.run_night(2026, 9, 14)), 1)
        self.assertEqual(self.run_night(2026, 9, 14), [])
        self.assertEqual(self.run_night(2026, 9, 20), [])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 1)

    def test_bad_box_score_stops_before_any_money_moves(self):
        self.feed.boxes["g1"]["problems"] = ["passers threw for 300 yards but receivers caught 280"]
        L.trade(self.c, "you", self.a["ticker"], "buy", 100, eastern(2026, 9, 10))
        cash = L.cash_cents(self.c, "you")
        N.sync_schedule(self.c, self.feed, weeks=[1])
        with self.assertRaises(N.NotReady):
            N.fetch_day(self.c, "2026-09-13", self.feed)
        self.assertEqual(L.cash_cents(self.c, "you"), cash)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM payouts").fetchone()[0], 0)

    def test_unfinished_game_waits(self):
        self.feed.weeks[1][0]["status"] = "STATUS_IN_PROGRESS"
        N.sync_schedule(self.c, self.feed, weeks=[1])
        with self.assertRaises(N.NotReady):
            N.fetch_day(self.c, "2026-09-13", self.feed)

    def test_fair_value_moves_and_week_rechecks(self):
        before_a, before_b = self.a["fair_value"], self.b["fair_value"]
        [report] = self.run_night(2026, 9, 14)
        after = {r["id"]: r["fair_value"] for r in self.c.execute("SELECT id, fair_value FROM athletes")}
        self.assertGreater(after[self.a["id"]], before_a)   # 26 points: price up
        self.assertLess(after[self.b["id"]], before_b)      # a zero: price down
        self.assertEqual({c["week"] for c in report["group_checks"]}, {1})   # the only game of week 1 is done
        for g in report["group_checks"]:
            self.assertLessEqual(abs(g["after"] - 1), ECON["live"]["recheck_max_move"] + 1e-12)

    def test_playoff_boost(self):
        N.sync_schedule(self.c, self.feed, weeks=[1])
        self.c.execute("UPDATE games SET playoff = 1")
        L.trade(self.c, "you", self.a["ticker"], "buy", 10, eastern(2026, 9, 10))
        self.run_night(2026, 9, 14)
        d = self.c.execute("SELECT cents FROM dividends").fetchone()["cents"]
        self.assertEqual(d, round(10 * 26.0 * self.rate * ECON["live"]["playoff_boost"] * 100))

    def test_dividend_rounding_half_up(self):
        self.assertEqual(N.dividend_cents(1, 1.0, 0.005, 1.0), 1)      # half a cent rounds up
        self.assertEqual(N.dividend_cents(1, 1.0, 0.00499, 1.0), 0)


if __name__ == "__main__":
    unittest.main()
