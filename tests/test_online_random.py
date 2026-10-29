"""A long random run of orders, cancels, fair value moves, games and overnight sweeps in one league on the Supabase
TEST project (skipped without its keys). After every step the books must add up (check_league), and outside games
nothing may be left waiting that should have filled: no waiting buy at or above a waiting sale or the market maker's
selling price, no waiting sale at or below his buying price."""
import random
import unittest

import online
from engine.online import OnlineError
from test_online_trading import START, today  # noqa: F401  (START: the league's starting cash)

ATHLETES = [online.athlete_id("CCC"), online.athlete_id("CCC", 2), online.athlete_id("DDD")]
STEPS = 70


class RandomRun(unittest.TestCase):
    def test_random_run(self):
        online.project()
        online.ensure_season()
        online.reset_season()
        robot = online.project()[0]
        players = online.phones(4)
        got = players[0].rpc("create_league", p_name="Random run", p_season=online.SEASON,
                             p_starts_on=today().isoformat(), p_ends_on=today().isoformat(), p_display_name="P1")
        m = got["market_id"]
        for ph in players[1:]:
            ph.rpc("join_league", p_code=got["join_code"], p_display_name=f"P{ph.n}")
        rng = random.Random(1029)
        in_game = False
        counts = {"filled": 0, "refused": 0}
        try:
            for step in range(STEPS):
                ph, a = rng.choice(players), rng.choice(ATHLETES)
                r = rng.random()
                try:
                    if r < 0.05:
                        online.set_fair_value(a, round(rng.uniform(40, 60), 2))
                        robot.rpc("sweep_league", p_market=m)
                    elif r < 0.08 and not in_game:
                        online.kick_off("CCC")
                        in_game = True
                    elif r < 0.11 and in_game:
                        online.process("CCC")
                        robot.rpc("sweep_league", p_market=m)
                        in_game = False
                    elif r < 0.2:
                        mine = ph.rpc("my_account", p_market=m)["open_orders"]
                        if mine:
                            ph.rpc("cancel_order", p_order=rng.choice(mine)["id"])
                    else:
                        side = rng.choice(["buy", "buy", "sell"])
                        shares = rng.choice([1, 5, 20, 60, 150])
                        if rng.random() < 0.4:
                            pv = ph.rpc("place_order", p_market=m, p_athlete=a, p_side=side, p_kind="market",
                                        p_shares=shares, p_preview=True)
                            res = ph.rpc("place_order", p_market=m, p_athlete=a, p_side=side, p_kind="market",
                                         p_shares=shares, p_limit_cents=pv["worst_cents"] or 1)
                            if res["filled"] == pv["filled"]:
                                self.assertEqual(res["cents"], pv["cents"], f"step {step}: preview differs from fill")
                        else:
                            price = int(rng.gauss(5050, 150))
                            res = ph.rpc("place_order", p_market=m, p_athlete=a, p_side=side, p_kind="limit",
                                         p_shares=shares, p_limit_cents=price)
                        counts["filled"] += res["filled"]
                except OnlineError as e:
                    if not any(w in str(e) for w in ("free", "waiting at", "on offer", "Cancel it")):
                        raise
                    counts["refused"] += 1
                self.assertEqual(robot.rpc("check_league", p_market=m), [], f"step {step}")
                if not in_game:
                    for x in ATHLETES:
                        self.assert_uncrossed(players[0], m, x, step)
        finally:
            online.reset_season()
        self.assertGreater(counts["filled"], 200)

    def assert_uncrossed(self, ph, m, a, step):
        book = ph.rpc("order_book", p_market=m, p_athlete=a)
        bid = book["bids"][0]["price"] if book["bids"] else None
        ask = book["asks"][0]["price"] if book["asks"] else None
        mm = book["market_maker"]
        where = f"step {step}, {a}: {book}"
        if bid is not None and ask is not None:
            self.assertLess(bid, ask, where)
        if bid is not None:
            self.assertLess(bid, mm["sells_from_cents"], where)
        if ask is not None and mm["buys_from_cents"] is not None:
            self.assertGreater(ask, mm["buys_from_cents"], where)


if __name__ == "__main__":
    unittest.main()
