"""The order book's rules (MILESTONE_2_PLAN.md), tested the way phones will use them: signed-in test users calling the
database functions on the Supabase TEST project. Skipped without its keys.

Each test makes its own league on the pretend season 'zz-test' (fair value $50, 100 shares per 1% step, the usual
market maker levers), and ends with the database's own check that the league's books add up (check_league)."""
import threading
import unittest
from datetime import datetime, timedelta, timezone

import online
from engine import ledger as L, market_maker as MM
from engine.online import OnlineError

A1, A2, B1 = online.athlete_id("AAA"), online.athlete_id("AAA", 2), online.athlete_id("BBB")
START = 10_000_000  # $100,000 in cents

def today():
    return datetime.now(timezone.utc).astimezone(L.EASTERN).date()


class Trading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        online.project()
        online.ensure_season()
        cls.p = online.phones(20)
        cls.robot = online.project()[0]
        online.reset_season()

    def setUp(self):
        self.leagues = []

    def tearDown(self):
        online.reset_season()
        for m in self.leagues:
            self.assertEqual(self.robot.rpc("check_league", p_market=m), [])

    # ---- helpers

    def league(self, players=2, starts=None, ends=None):
        starts = starts or today()
        got = self.p[0].rpc("create_league", p_name="Test league", p_season=online.SEASON,
                            p_starts_on=starts.isoformat(), p_ends_on=(ends or starts + timedelta(days=60)).isoformat(),
                            p_display_name="P1")
        for ph in self.p[1:players]:
            ph.rpc("join_league", p_code=got["join_code"], p_display_name=f"P{ph.n}")
        self.leagues.append(got["market_id"])
        return got["market_id"]

    def order(self, ph, m, a, side, kind, shares, limit=None, preview=False):
        return ph.rpc("place_order", p_market=m, p_athlete=a, p_side=side, p_kind=kind, p_shares=shares,
                      p_limit_cents=limit, p_preview=preview)

    def market(self, ph, m, a, side, shares):
        """Preview, then place with the preview's worst price as the guard, as the phone will."""
        pv = self.order(ph, m, a, side, "market", shares, preview=True)
        return self.order(ph, m, a, side, "market", shares, pv["worst_cents"])

    def account(self, ph, m):
        return ph.rpc("my_account", p_market=m)

    def held(self, ph, m, a):
        return next((h["shares"] for h in self.account(ph, m)["holdings"] if h["athlete_id"] == a), 0)

    def refused(self, pattern, fn, *args, **kw):
        with self.assertRaisesRegex(OnlineError, pattern):
            fn(*args, **kw)

    def in_game(self, team="AAA"):
        online.kick_off(team)

    def overnight(self, m, team="AAA"):
        online.process(team)
        return self.robot.rpc("sweep_league", p_market=m)

    def rows(self, table, **filters):
        return self.robot.select(table, **filters)

    # ---- leagues

    def test_create_and_join(self):
        got = self.p[0].rpc("create_league", p_name="  Sunday Club ", p_season=online.SEASON,
                            p_starts_on=today().isoformat(), p_ends_on=(today() + timedelta(days=9)).isoformat(),
                            p_display_name="Justin")
        self.leagues.append(got["market_id"])
        self.assertRegex(got["join_code"], r"^[A-HJ-NP-Z2-9]{6}$")
        j = self.p[1].rpc("join_league", p_code=got["join_code"].lower(), p_display_name="Dad")
        self.assertEqual(j["market_id"], got["market_id"])
        self.assertEqual(self.p[1].rpc("join_league", p_code=got["join_code"], p_display_name="Other")["member_id"],
                         j["member_id"])  # joining twice changes nothing
        self.refused("already uses the name", self.p[2].rpc, "join_league", p_code=got["join_code"],
                     p_display_name="justin")
        self.refused("No league has the code", self.p[2].rpc, "join_league", p_code="ZZZZZZ", p_display_name="X")
        acct = self.account(self.p[1], got["market_id"])
        self.assertEqual((acct["cash_cents"], acct["free_cents"]), (START, START))
        self.refused("only|Only", self.p[1].rpc, "new_join_code", p_market=got["market_id"])
        self.assertNotEqual(self.p[0].rpc("new_join_code", p_market=got["market_id"])["join_code"], got["join_code"])
        self.refused("aren't in this league", self.p[3].rpc, "order_book", p_market=got["market_id"], p_athlete=A1)

    def test_full_league(self):
        m = self.league(2)
        self.robot.update("markets", {"max_players": 2}, id=f"eq.{m}")
        code = self.rows("markets", id=f"eq.{m}")[0]["join_code"]
        self.refused("full", self.p[2].rpc, "join_league", p_code=code, p_display_name="P3")

    def test_no_trading_before_the_start_or_after_the_end(self):
        m = self.league(1, starts=today() + timedelta(days=1))
        self.refused("Trading starts on", self.market, self.p[0], m, A1, "buy", 10)
        m = self.league(1, starts=today(), ends=today())
        self.order(self.p[0], m, A1, "buy", "limit", 10, 4000)
        ended = self.robot.rpc("end_leagues", p_today=(today() + timedelta(days=1)).isoformat())
        self.assertIn(m, ended)
        orders = self.rows("orders", market_id=f"eq.{m}", select="status,close_reason")
        self.assertEqual(orders, [{"status": "cancelled", "close_reason": "league over"}])
        self.refused("league is over", self.order, self.p[0], m, A1, "buy", "limit", 10, 4000)

    # ---- the market maker

    def test_buy_and_sell_with_the_market_maker_match_python(self):
        m = self.league(1)
        got = self.market(self.p[0], m, A1, "buy", 250)
        self.assertEqual((got["filled"], got["status"]), (250, "filled"))
        self.assertEqual(got["cents"], MM.buy_cost_cents(50.0, 0, 250, 100.0, online.MM))
        got = self.market(self.p[0], m, A1, "sell", 100)
        self.assertEqual(got["cents"], MM.sell_proceeds_cents(50.0, 250, 100, 100.0, online.MM))
        acct = self.account(self.p[0], m)
        self.assertEqual(acct["cash_cents"], START - MM.buy_cost_cents(50.0, 0, 250, 100.0, online.MM)
                         + MM.sell_proceeds_cents(50.0, 250, 100, 100.0, online.MM))
        self.assertEqual(acct["holdings"][0]["shares"], 150)
        self.assertEqual(acct["holdings"][0]["value_cents"], MM.sell_proceeds_cents(50.0, 150, 150, 100.0, online.MM))
        book = self.p[0].rpc("order_book", p_market=m, p_athlete=A1)["market_maker"]
        self.assertEqual(book["sells_from_cents"], MM.buy_cost_cents(50.0, 150, 1, 100.0, online.MM))

    def test_a_waiting_buy_fills_at_the_market_makers_price_not_its_own(self):
        m = self.league(1)
        got = self.order(self.p[0], m, A1, "buy", "limit", 10, 4900)
        self.assertEqual((got["status"], got["filled"], got["waiting"]), ("open", 0, 10))
        self.assertEqual(self.account(self.p[0], m)["set_aside_cents"], 49000)
        online.set_fair_value(A1, 45.0)
        fills = self.robot.rpc("sweep_league", p_market=m)
        cost = MM.buy_cost_cents(45.0, 0, 10, 100.0, online.MM)
        self.assertEqual([(f["shares"], f["cents"]) for f in fills], [(10, cost)])
        acct = self.account(self.p[0], m)
        self.assertEqual((acct["cash_cents"], acct["set_aside_cents"]), (START - cost, 0))  # the difference is released

    # ---- player to player

    def test_waiting_price_wins_best_price_first_and_players_before_the_market_maker(self):
        m = self.league(3)
        for ph in self.p[:2]:
            self.market(ph, m, A1, "buy", 40)
        # P1 offers 20 at $50.40 and P2 20 at $50.30, both below the market maker's price (about $51.4)
        self.order(self.p[0], m, A1, "sell", "limit", 20, 5040)
        self.order(self.p[1], m, A1, "sell", "limit", 20, 5030)
        book = self.p[2].rpc("order_book", p_market=m, p_athlete=A1)
        self.assertEqual([(x["price"], x["shares"]) for x in book["asks"]], [(5030, 20), (5040, 20)])
        held = 80
        got = self.order(self.p[2], m, A1, "buy", "limit", 60, 6000)
        mm_cost = MM.buy_cost_cents(50.0, held, 20, 100.0, online.MM)
        self.assertEqual((got["filled"], got["from_players"], got["pieces"]), (60, 40, 3))
        self.assertEqual(got["cents"], 20 * 5030 + 20 * 5040 + mm_cost)  # each player's own price, then the mm's
        trades = self.rows("trades", buy_order_id=f"eq.{got['order_id']}", order="id")
        self.assertEqual([(t["shares"], t["cents"], t["seller_id"] is None) for t in trades],
                         [(20, 100600, False), (20, 100800, False), (20, mm_cost, True)])

    def test_a_player_goes_before_the_market_maker_at_the_same_price(self):
        m = self.league(2)
        flat = {"spread": 0.0, "lean_per_step": 0.0}  # the market maker's price is exactly $50.00 for every share
        self.market(self.p[0], m, A1, "buy", 10)
        self.order(self.p[0], m, A1, "sell", "limit", 10, 5000)  # waits: the market maker buys at about $49.05
        self.robot.update("markets", {"mm": flat}, id=f"eq.{m}")
        got = self.order(self.p[1], m, A1, "buy", "limit", 15, 5000)
        self.assertEqual((got["filled"], got["from_players"], got["cents"]), (15, 10, 75000))

    def test_you_cant_trade_with_yourself(self):
        m = self.league(1)
        self.market(self.p[0], m, A1, "buy", 10)
        self.order(self.p[0], m, A1, "sell", "limit", 10, 5050)
        self.refused(r"You have a sell waiting at \$50.50. Cancel it first.", self.order, self.p[0], m, A1, "buy",
                     "limit", 5, 5100)
        self.refused("sell waiting", self.order, self.p[0], m, A1, "buy", "market", 5, preview=True)
        self.order(self.p[0], m, A1, "buy", "limit", 5, 4000)  # below his own offer: fine

    # ---- money set aside

    def test_cash_and_shares_cant_be_promised_twice(self):
        m = self.league(1)
        self.order(self.p[0], m, A1, "buy", "limit", 2000, 4500)  # sets aside $90,000
        self.refused(r"Not enough free cash: .* you have \$10,000.00 free", self.order, self.p[0], m, A2, "buy",
                     "limit", 300, 4000)
        got = self.market(self.p[0], m, A2, "buy", 10_000)  # a market buy stops where free cash runs out
        self.assertLess(got["filled"], 10_000)
        self.assertEqual(got["dropped"], 10_000 - got["filled"])
        self.assertLessEqual(got["cents"], 1_000_000)
        self.refused("can't sell 500", self.order, self.p[0], m, A2, "sell", "limit", 500, 6000)
        self.order(self.p[0], m, A2, "sell", "limit", got["filled"], 6000)
        self.refused("You have 0", self.market, self.p[0], m, A2, "sell", 1)

    def test_cancel(self):
        m = self.league(2)
        got = self.order(self.p[0], m, A1, "buy", "limit", 100, 4000)
        self.refused("isn't your order", self.p[1].rpc, "cancel_order", p_order=got["order_id"])
        self.assertEqual(self.p[0].rpc("cancel_order", p_order=got["order_id"])["released"], 100)
        self.refused("already cancelled", self.p[0].rpc, "cancel_order", p_order=got["order_id"])
        self.assertEqual(self.account(self.p[0], m)["free_cents"], START)

    # ---- market orders and the preview

    def test_preview_is_the_fill_and_leaves_nothing_behind(self):
        m = self.league(3)
        self.market(self.p[0], m, A1, "buy", 30)
        self.order(self.p[0], m, A1, "sell", "limit", 30, 5080)
        count = lambda: (len(self.rows("orders", market_id=f"eq.{m}")), len(self.rows("trades", market_id=f"eq.{m}")))  # noqa: E731,E501
        before = count()
        pv = self.order(self.p[1], m, A1, "buy", "market", 120, preview=True)
        self.assertEqual(count(), before)
        got = self.order(self.p[1], m, A1, "buy", "market", 120, pv["worst_cents"])
        for k in ("filled", "cents", "worst_cents", "from_players", "pieces"):
            self.assertEqual(got[k], pv[k], k)
        self.assertTrue(pv["preview"])

    def test_market_order_price_guard_gives_fewer_shares_never_a_worse_price(self):
        m = self.league(2)
        pv = self.order(self.p[0], m, A1, "buy", "market", 100, preview=True)
        self.market(self.p[1], m, A1, "buy", 50)  # the price moves up between the preview and the tap
        got = self.order(self.p[0], m, A1, "buy", "market", 100, pv["worst_cents"])
        self.assertEqual(got["status"], "cancelled")
        self.assertLess(got["filled"], 100)
        self.assertLessEqual(got["worst_cents"], pv["worst_cents"])
        self.assertEqual(got["cents"], MM.buy_cost_cents(50.0, 50, got["filled"], 100.0, online.MM))

    # ---- during games

    def test_market_order_fills_what_is_on_offer_while_the_market_maker_is_out(self):
        m = self.league(2)
        self.market(self.p[0], m, A1, "buy", 30)
        self.in_game()
        self.order(self.p[0], m, A1, "sell", "limit", 30, 5200)  # placed during the game: live
        pv = self.order(self.p[1], m, A1, "buy", "market", 50, preview=True)
        self.assertEqual((pv["filled"], pv["market_maker_out"]), (30, True))
        got = self.order(self.p[1], m, A1, "buy", "market", 50, pv["worst_cents"])
        self.assertEqual((got["filled"], got["dropped"], got["cents"], got["status"]), (30, 20, 156000, "cancelled"))
        self.refused("market maker is out while", self.order, self.p[1], m, A1, "buy", "market", 5, 9999)
        self.market(self.p[1], m, B1, "buy", 5)  # another team's player still trades with the market maker

    def test_orders_placed_before_kickoff_sleep_through_the_game(self):
        m = self.league(3)
        self.market(self.p[0], m, A1, "buy", 40)
        self.market(self.p[2], m, A1, "buy", 10)
        asleep = self.order(self.p[0], m, A1, "sell", "limit", 40, 5050)
        self.in_game()
        book = self.p[1].rpc("order_book", p_market=m, p_athlete=A1)
        self.assertEqual(book["asks"], [{"price": 5050, "shares": 40, "asleep": 40}])
        self.refused("on offer", self.order, self.p[1], m, A1, "buy", "market", 5, 9999)
        self.order(self.p[2], m, A1, "sell", "limit", 10, 5060)  # placed during the game: live
        got = self.order(self.p[1], m, A1, "buy", "limit", 15, 5100)
        self.assertEqual((got["filled"], got["cents"], got["waiting"]), (10, 50600, 5))  # skips the cheaper sleeper
        self.overnight(m)
        got = self.market(self.p[1], m, A1, "buy", 10)  # awake again, and cheaper than the market maker
        self.assertEqual((got["filled"], got["from_players"], got["cents"]), (10, 10, 50500))
        rest = self.rows("orders", id=f"eq.{asleep['order_id']}", select="remaining")
        self.assertEqual(rest, [{"remaining": 25}])  # 5 to the waking buy overnight (at $50.50, the older order's price), 10 now

    # ---- two people at once

    def test_twenty_orders_at_once_for_the_last_fifty_shares(self):
        m = self.league(20)
        self.market(self.p[0], m, A1, "buy", 50)
        self.in_game()  # the market maker is out: the 50 below are the only shares on offer
        self.order(self.p[0], m, A1, "sell", "limit", 50, 5500)
        buyers = self.p[1:] + [self.p[1]]  # 20 orders from 19 players
        results, errors = [], []

        def go(ph):
            try:
                results.append(self.order(ph, m, A1, "buy", "limit", 10, 6000))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=go, args=(ph,)) for ph in buyers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 20)
        self.assertEqual(sum(r["filled"] for r in results), 50)
        self.assertTrue(all(r["cents"] == r["filled"] * 5500 for r in results))
        trades = self.rows("trades", market_id=f"eq.{m}", seller_id="not.is.null")
        self.assertEqual(sum(t["shares"] for t in trades), 50)
        self.assertEqual(self.held(self.p[0], m, A1), 0)

    # ---- the leaderboard

    def test_leaderboard_values_holdings_at_the_market_makers_selling_price(self):
        m = self.league(2)
        cost = self.market(self.p[0], m, A1, "buy", 100)["cents"]
        self.in_game()  # so the market maker can't fill the silly bid below
        self.order(self.p[1], m, A1, "buy", "limit", 100, 9000)  # a silly bid doesn't raise anyone's worth
        board = {r["display_name"]: r for r in self.p[1].rpc("leaderboard", p_market=m)}
        value = MM.sell_proceeds_cents(50.0, 100, 100, 100.0, online.MM)
        self.assertEqual(board["P1"]["net_worth_cents"], START - cost + value)
        self.assertEqual(board["P2"]["net_worth_cents"], START)


if __name__ == "__main__":
    unittest.main()
