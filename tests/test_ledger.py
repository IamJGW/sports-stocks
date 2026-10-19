import sqlite3
import unittest

from helpers import ECON, eastern, new_market, utc
from engine import ledger as L

NOW = utc(2026, 9, 2)


class Trading(unittest.TestCase):
    def setUp(self):
        self.c = new_market()
        self.a = self.c.execute("SELECT * FROM athletes ORDER BY start_price DESC LIMIT 1").fetchone()

    def test_buy_then_sell_moves_cash_and_shares(self):
        t = L.trade(self.c, "you", self.a["ticker"], "buy", 100, NOW)
        self.assertEqual(L.shares_held(self.c, "you", self.a["id"]), 100)
        self.assertEqual(L.cash_cents(self.c, "you"), 100_000_00 + t["cents"])
        s = L.trade(self.c, "you", self.a["ticker"], "sell", 100, NOW)
        self.assertEqual(L.shares_held(self.c, "you", self.a["id"]), 0)
        self.assertLess(L.cash_cents(self.c, "you"), 100_000_00)       # the spread was paid
        self.assertEqual(L.cash_cents(self.c, "you"), 100_000_00 + t["cents"] + s["cents"])

    def test_cannot_overspend_or_oversell_or_trade_fractions(self):
        with self.assertRaises(L.TradeRefused):
            L.trade(self.c, "you", self.a["ticker"], "buy", 100_000, NOW)
        with self.assertRaises(L.TradeRefused):
            L.trade(self.c, "you", self.a["ticker"], "sell", 1, NOW)
        for bad in (0, -5, 2.5):
            with self.assertRaises(L.TradeRefused):
                L.trade(self.c, "you", self.a["ticker"], "buy", bad, NOW)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_price_moved_since_preview_is_refused(self):
        q = L.quote_trade(self.c, "you", self.a["ticker"], "buy", 50, NOW)
        L.trade(self.c, "you", self.a["ticker"], "buy", 500, NOW)        # pushes the price up
        with self.assertRaises(L.TradeRefused):
            L.trade(self.c, "you", self.a["ticker"], "buy", 50, NOW, expect_cents=q["cents"])

    def test_trades_and_dividends_cannot_be_edited(self):
        L.trade(self.c, "you", self.a["ticker"], "buy", 10, NOW)
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.execute("UPDATE trades SET cents = 0")
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.execute("DELETE FROM trades")

    def test_market_maker_steps_out_from_kickoff_until_processed(self):
        team = self.a["team"]
        self.c.execute("INSERT INTO games (id, week, kickoff, day, home, away, status) VALUES "
                       "('g1', 1, ?, '2026-09-13', ?, 'ZZZ', 'STATUS_IN_PROGRESS')",
                       (L.utc_text(eastern(2026, 9, 13, 13)), team))
        L.trade(self.c, "you", self.a["ticker"], "buy", 10, eastern(2026, 9, 13, 12, 59))   # before kickoff: fine
        with self.assertRaises(L.TradeRefused):
            L.trade(self.c, "you", self.a["ticker"], "buy", 10, eastern(2026, 9, 13, 13, 30))
        with self.assertRaises(L.TradeRefused):
            L.trade(self.c, "you", self.a["ticker"], "sell", 10, eastern(2026, 9, 14, 3))     # still before the update
        self.c.execute("UPDATE games SET processed_at = 'x', status = 'STATUS_FINAL'")
        L.trade(self.c, "you", self.a["ticker"], "sell", 10, eastern(2026, 9, 14, 5))

    def test_net_worth_values_holdings_at_what_selling_them_brings(self):
        L.trade(self.c, "you", self.a["ticker"], "buy", 900, NOW)
        pf = L.portfolio(self.c, "you", NOW)
        self.assertLess(pf["net_worth_cents"], 100_000_00)
        held = pf["holdings"][0]
        back = L.quote_trade(self.c, "you", self.a["ticker"], "sell", 900, NOW)["cents"]
        self.assertEqual(held["value_cents"], back)

    def test_record_time_is_midnight_eastern(self):
        self.assertEqual(L.record_time("2026-09-13"), "2026-09-13T04:00:00Z")   # EDT
        self.assertEqual(L.record_time("2026-12-06"), "2026-12-06T05:00:00Z")   # EST


if __name__ == "__main__":
    unittest.main()
