import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from helpers import ECON, ROOT, eastern, new_market, utc
from engine import api, ledger as L, pricing

sys.path.insert(0, ROOT)
import serve  # noqa: E402

NOW = utc(2026, 9, 2)


class Api(unittest.TestCase):
    def setUp(self):
        self.c = new_market()
        self.a = self.c.execute("SELECT * FROM athletes ORDER BY start_price DESC LIMIT 1").fetchone()

    def test_refusals_come_back_as_messages_for_the_page(self):
        q = api.quote(self.c, self.a["ticker"], "buy", 100_000, NOW)
        self.assertFalse(q["ok"])
        self.assertIn("Not enough cash", q["message"])
        q = api.quote(self.c, self.a["ticker"], "sell", 1, NOW)
        self.assertIn("You hold 0", q["message"])
        r = api.place_trade(self.c, self.a["ticker"], "buy", 0, None, NOW)
        self.assertFalse(r["ok"])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_in_a_game_message_and_flag(self):
        self.c.execute("INSERT INTO games (id, week, kickoff, day, home, away, status) VALUES "
                       "('g1', 1, ?, '2026-09-13', ?, 'ZZZ', 'STATUS_IN_PROGRESS')",
                       (L.utc_text(eastern(2026, 9, 13, 13)), self.a["team"]))
        during = eastern(2026, 9, 13, 14)
        q = api.quote(self.c, self.a["ticker"], "buy", 10, during)
        self.assertFalse(q["ok"])
        self.assertIn("in a game", q["message"])
        page = api.athlete_page(self.c, self.a["ticker"], during)
        self.assertTrue(page["in_game"])
        self.assertEqual(page["max_buy"], 0)
        self.assertTrue(next(m for m in api.market(self.c, during)["athletes"] if m["ticker"] == self.a["ticker"])["in_game"])

    def test_preview_matches_the_trade(self):
        q = api.quote(self.c, self.a["ticker"], "buy", 50, NOW)
        self.assertTrue(q["ok"])
        r = api.place_trade(self.c, self.a["ticker"], "buy", 50, q["expect_cents"], NOW)
        self.assertEqual(r["cents"], q["total_cents"])
        self.assertEqual(api.portfolio(self.c, NOW)["holdings"][0]["shares"], 50)
        self.assertEqual(api.athlete_page(self.c, self.a["ticker"], NOW)["mine"], 50)

    def test_all_in_amount_is_the_most_cash_can_buy(self):
        page = api.athlete_page(self.c, self.a["ticker"], NOW)
        n = page["max_buy"]
        self.assertTrue(api.quote(self.c, self.a["ticker"], "buy", n, NOW)["ok"])
        self.assertFalse(api.quote(self.c, self.a["ticker"], "buy", n + 1, NOW)["ok"])

    def test_report_with_no_report_yet(self):
        self.assertIsNone(api.latest_report(self.c)["report"])


class Http(unittest.TestCase):
    def test_round_trip_through_the_server(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "save.sqlite")
        conn = L.connect(path)
        L.create_game(conn, ECON, pricing.load_csv(os.path.join(ROOT, "data", "nfl_2025.csv")), "NFL", 2026,
                      "you", "Tester", utc(2026, 9, 1))
        conn.close()
        server = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(path, clock=lambda: NOW))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            get = lambda p: json.load(urllib.request.urlopen(base + p))
            market = get("/api/market")["athletes"]
            self.assertEqual(len(market), 120)
            t = market[0]["ticker"]
            q = get(f"/api/quote?ticker={t}&side=buy&shares=10")
            req = urllib.request.Request(base + "/api/trade", method="POST", headers={"Content-Type": "application/json"},
                                         data=json.dumps({"ticker": t, "side": "buy", "shares": 10,
                                                          "expect_cents": q["expect_cents"]}).encode())
            self.assertTrue(json.load(urllib.request.urlopen(req))["ok"])
            self.assertEqual(get("/api/portfolio")["holdings"][0]["shares"], 10)
            bad = get(f"/api/quote?ticker={t}&side=sell&shares=999")
            self.assertIn("You hold 10", bad["message"])
            self.assertIn("Sports Stocks", urllib.request.urlopen(base + "/").read().decode())
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/../serve.py")
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
