"""The market maker's prices in the database agree with engine/market_maker.py to the cent: thousands of random blocks,
the edges (one share, no lean, huge holdings), and every trade in the Mac's save. Runs against the Supabase TEST
project; skipped without its keys."""
import json
import os
import random
import sqlite3
import unittest

import online
from engine import market_maker as MM

SAVE = os.path.join(online.ROOT, "save", "game.sqlite")


def db_prices(cases):
    """[(fair_value, held, n, step_shares, mm)] -> [(buy cost, sell proceeds)] from the database, in one request."""
    rows = [{"i": i, "fv": fv, "held": held, "n": n, "step": step, "mm": mm}
            for i, (fv, held, n, step, mm) in enumerate(cases)]
    got = online.sql(f"""
        select x.i, private.mm_buy_cost_cents(x.fv, x.held, x.n, x.step, x.mm) as buy,
               case when x.held >= x.n then private.mm_sell_proceeds_cents(x.fv, x.held, x.n, x.step, x.mm) end as sell
        from jsonb_to_recordset({online.lit(rows)}::jsonb)
             as x(i int, fv double precision, held bigint, n bigint, step double precision, mm jsonb)
        order by x.i""")
    return [(r["buy"], r["sell"]) for r in got]


def py_prices(cases):
    return [(MM.buy_cost_cents(fv, held, n, step, mm),
             MM.sell_proceeds_cents(fv, held, n, step, mm) if held >= n else None)
            for fv, held, n, step, mm in cases]


class MarketMakerParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        online.project()

    def check(self, cases):
        for i in range(0, len(cases), 2000):
            part = cases[i:i + 2000]
            self.assertEqual(db_prices(part), py_prices(part))

    def test_random_blocks(self):
        rng = random.Random(20261029)
        cases = []
        for _ in range(6000):
            fv = round(rng.uniform(0.5, 400), rng.choice([0, 2, 6, 12]))
            step = rng.choice([5000 / fv, round(rng.uniform(5, 2000), 3), 100.0])
            mm = {"spread": rng.choice([0.04, 0.0, 0.1, 0.025]), "lean_per_step": rng.choice([0.01, 0.0, 0.005, 0.03])}
            held = rng.choice([0, 1, rng.randint(0, 200), rng.randint(0, 20000)])
            n = rng.choice([1, 2, rng.randint(1, 100), rng.randint(1, 5000)])
            if MM.buy_cost_cents(fv, held, n, step, mm) < 10 ** 12:  # past $10 billion is no league's price
                cases.append((fv, held, n, step, mm))
        self.assertGreater(len(cases), 4000)
        self.check(cases)

    def test_edges(self):
        mm = {"spread": 0.04, "lean_per_step": 0.01}
        cases = [(50.0, 0, 1, 100.0, mm), (50.0, 1, 1, 100.0, mm), (49.99, 0, 1, 100.0, {"spread": 0.0,
                 "lean_per_step": 0.0}), (0.01, 0, 1, 1.0, mm), (1000.0, 2000, 3000, 5.0, mm),
                 (37.5, 250, 250, 133.33333333333334, mm), (12.345678, 3, 3, 405.0, mm)]
        self.check(cases)

    def test_every_trade_in_the_save(self):
        if not os.path.exists(SAVE):
            self.skipTest("no save on this Mac")
        conn = sqlite3.connect(SAVE)
        conn.row_factory = sqlite3.Row
        mm = json.loads(conn.execute("SELECT value FROM meta WHERE key = 'economy'").fetchone()[0])["market_maker"]
        trades = conn.execute("SELECT t.*, a.step_shares FROM trades t JOIN athletes a ON a.id = t.athlete_id").fetchall()
        self.assertTrue(trades)
        cases = [(t["fair_value"], t["market_held_before"], abs(t["shares"]), t["step_shares"], mm) for t in trades]
        got = db_prices(cases)
        for t, (buy, sell) in zip(trades, got):
            self.assertEqual(-buy if t["shares"] > 0 else sell, t["cents"], dict(t))


if __name__ == "__main__":
    unittest.main()
