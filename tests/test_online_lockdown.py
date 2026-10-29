"""Against the Supabase TEST project (skipped without its keys): phones can't write anything, a phone that isn't signed
in can't even read, and stat lines, payouts, trades and dividends can't be changed once written."""
import unittest

import online
from engine.online import OnlineError
from tools import db

SHARED = ["seasons", "athletes", "groups", "group_checks", "games", "stat_lines", "payouts", "fair_values",
          "robot_status"]
LEAGUE = ["markets", "members", "orders", "trades", "dividends", "reports"]


class Lockdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        online.project()

    def test_safety_check(self):
        problems = online.sql(db.SAFETY)
        allowed = db.phone_functions()
        self.assertEqual([p for p in problems if not (p["problem"] == "callable by phones"
                                                      and p["name"] in allowed)], [])

    def test_not_signed_in_reads_and_writes_nothing(self):
        anon = online.anonymous()
        for t in SHARED + LEAGUE:
            with self.assertRaises(OnlineError, msg=t):
                anon.select(t, limit=1)
            with self.assertRaises(OnlineError, msg=t):
                anon.request("POST", t, {"id": "x"})

    def test_signed_in_phone_reads_shared_but_writes_nothing(self):
        phone = online.phones(1)[0]
        self.assertTrue(phone.select("athletes", limit=1))
        for t in SHARED + LEAGUE:
            with self.assertRaises(OnlineError, msg=t):
                phone.request("POST", t, {"id": "x"})
            with self.assertRaises(OnlineError, msg=t):
                phone.request("PATCH", f"{t}?id=eq.x", {"id": "y"})
            with self.assertRaises(OnlineError, msg=t):
                phone.request("DELETE", f"{t}?id=eq.x")

    def test_signed_in_phone_sees_no_league_it_isnt_in(self):
        phone = online.phones(1)[0]
        mine = {r["market_id"] for r in phone.select("members", user_id=f"eq.{phone.user_id}")}
        for t in ["members", "trades", "dividends", "reports"]:
            self.assertTrue({r["market_id"] for r in phone.select(t)} <= mine, t)
        self.assertTrue({r["id"] for r in phone.select("markets")} <= mine)

    def test_money_rows_are_final(self):
        with self.assertRaisesRegex(OnlineError, "final"):
            online.sql("update public.payouts set per_share = per_share + 1 "
                       "where (game_id, athlete_id) = (select game_id, athlete_id from public.payouts limit 1)")
        with self.assertRaisesRegex(OnlineError, "final"):
            online.sql("delete from public.stat_lines where game_id = (select game_id from public.stat_lines limit 1)")
        triggers = {r["tgname"] for r in online.sql(
            "select tgname from pg_trigger where tgrelid in ('public.trades'::regclass, 'public.dividends'::regclass,"
            " 'public.orders'::regclass) and not tgisinternal")}
        self.assertEqual(triggers, {"trades_are_final", "dividends_are_final", "orders_guard"})


if __name__ == "__main__":
    unittest.main()
