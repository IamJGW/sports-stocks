import unittest

from helpers import ECON
from engine import market_maker as MM

M = ECON["market_maker"]


class MarketMaker(unittest.TestCase):
    def test_round_trip_always_loses(self):
        for fv in (3.17, 28.0, 50.0, 112.45):
            step = M["dollars_per_step"] / fv
            for held in (0, 7, 250, 5000):
                for n in (1, 13, 100, 2000):
                    cost = MM.buy_cost_cents(fv, held, n, step, M)
                    back = MM.sell_proceeds_cents(fv, held + n, n, step, M)
                    self.assertLess(back, cost, (fv, held, n))

    def test_block_costs_at_least_the_sum_of_singles(self):
        fv, step = 50.0, 100.0
        whole = MM.buy_cost_cents(fv, 0, 300, step, M)
        singles = sum(MM.buy_cost_cents(fv, h, 1, step, M) for h in range(300))
        exact = sum(MM.mid(fv, h, step, M) * (1 + M["spread"] / 2) for h in range(300)) * 100
        self.assertGreaterEqual(whole, exact)        # rounded up, never down
        self.assertLess(whole - exact, 1)            # by less than a cent
        self.assertLessEqual(whole, singles)         # splitting a block never saves money

    def test_first_share_price_matches_quote(self):
        fv, step = 50.0, 100.0
        bid, ask = MM.quote(fv, 400, step, M)
        self.assertAlmostEqual(MM.buy_cost_cents(fv, 400, 1, step, M) / 100, ask, delta=0.01)
        self.assertAlmostEqual(MM.sell_proceeds_cents(fv, 400, 1, step, M) / 100, bid, delta=0.01)

    def test_all_in_soft_cap_numbers_from_the_plan(self):
        n = MM.most_affordable(50.0, 0, 100_000_00, 100.0, M)
        self.assertEqual(n, 1791)
        self.assertAlmostEqual(MM.mid(50.0, n, 100.0, M), 59.75, delta=0.01)
        self.assertAlmostEqual(MM.sell_proceeds_cents(50.0, n, n, 100.0, M) / 100, 96060, delta=1)

    def test_steps_in_dollars_treat_cheap_and_dear_alike(self):
        # $25,000 of a $25 athlete and of a $100 athlete push each price up by the same share.
        for fv in (25.0, 100.0):
            step = M["dollars_per_step"] / fv
            n = int(25000 / fv)
            self.assertAlmostEqual(MM.mid(fv, n, step, M) / fv, 1.01 ** 5, places=9)


if __name__ == "__main__":
    unittest.main()
