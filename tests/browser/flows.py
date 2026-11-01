"""The browser flows in MILESTONE_ACCEPTANCE.md, in real Chrome at desktop and iPhone size.

  python3 tests/browser/flows.py                                 local, both sizes
  python3 tests/browser/flows.py --target live                   https://iamjgw.github.io/sports-stocks/, both sizes
  python3 tests/browser/flows.py --viewport iphone --only B08    one size, one flow (plus sign-in and a league)

Screenshots and results go to checks/browser/. The exit code is the number of failed flows.

Locally the page signs in fake @example.com testers: the request that would email them is stubbed so nothing bounces,
and the code comes from Supabase's admin generate_link. On the public site a person types the email and the code in the
Chrome window this opens; everything after that is scripted, and the sign-in stays in a named profile between runs.

The second player is a fake tester calling the same database functions the page calls. Everything runs against the
TEST project; this file never reads the live project's keys.
"""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import online  # noqa: E402
from chrome import Chrome, Failed  # noqa: E402
from engine import ledger as L  # noqa: E402

ROOT = online.ROOT
WEB = os.path.join(ROOT, "web")
OUT = os.path.join(ROOT, "checks", "browser")
LIVE_URL = "https://iamjgw.github.io/sports-stocks/"
PORT = 8671
SEASON = "nfl-2026"
HUMAN_WAIT = 20 * 60  # seconds a person gets to find the email and type the code

STUB_FETCH = """(() => { const real = window.fetch, stubs = %s;
  window.fetch = (u, o) => { const url = String(u?.url || u);
    for (const [k, v] of Object.entries(stubs)) if (url.includes(k))
      return Promise.resolve(new Response(JSON.stringify(v), { status: 200, headers: { 'content-type': 'application/json' } }));
    return real(u, o); }; })()"""
# Moves only `new Date()`, so the sign-in library's token clock (Date.now) stays true.
FAKE_CLOCK = """(() => { const R = Date, T = %d;
  function D(...a) { if (!new.target) return R(); return a.length ? new R(...a) : new R(T); }
  D.prototype = R.prototype; D.now = R.now; D.parse = R.parse; D.UTC = R.UTC; window.Date = D; })()"""
LAYOUT = """(() => { const out = [], mobile = %s, W = innerWidth, vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  if (document.documentElement.scrollWidth > W + 1) out.push('sideways scroll: ' + document.documentElement.scrollWidth + ' wide');
  document.querySelectorAll('main *, header *').forEach(e => { if (vis(e) && e.getBoundingClientRect().right > W + 1 && !e.closest('table')) out.push('past the edge: ' + e.tagName + '.' + e.className); });
  if (mobile) {
    document.querySelectorAll('input, select, textarea').forEach(e => { if (vis(e) && parseFloat(getComputedStyle(e).fontSize) < 16) out.push('input under 16px: #' + e.id); });
    document.querySelectorAll('nav a, button, a.row, a.help, a.back').forEach(e => { if (vis(e) && e.getBoundingClientRect().height < 32) out.push('tap target ' + Math.round(e.getBoundingClientRect().height) + 'px: ' + e.tagName + '.' + e.className + ' ' + e.innerText.slice(0, 16)); });
  }
  return [...new Set(out)]; })()"""


def today():
    return datetime.now(timezone.utc).astimezone(L.EASTERN).date()


def dollars(c):
    return f"${c / 100:,.2f}"


def cents_in(text):
    return round(float(re.search(r"\$([\d,]+\.\d\d)", text).group(1).replace(",", "")) * 100)


def check(ok, msg):
    if not ok:
        raise Failed(msg)


def eastern_ms(hour, minute):
    d = today()
    return int(datetime(d.year, d.month, d.day, hour, minute, tzinfo=L.EASTERN).timestamp() * 1000)


class Run:
    def __init__(self, target, viewport, base, tab, web):
        self.target, self.viewport, self.base, self.tab, self.web = target, viewport, base, tab, web
        self.live = target == "live"
        self.db = online.project()[0]
        self.b = online.phones(22)[21]   # the second player, tester22
        self.me_email = "tester21@example.com"
        self.name = f"{viewport.title()} player"
        self.stamp = secrets.token_hex(3)

    def shot(self, flow, tag=""):
        return self.tab.shot(os.path.join(OUT, f"{self.target}-{self.viewport}-{flow}{'-' + tag if tag else ''}.png"))

    # ---- Reading the database's side, not the page's

    def me(self):
        return self.tab.eval("rpc('my_account', { p_market: league.id }).then(r => r.member_id)")

    def account(self):
        return self.tab.eval("rpc('my_account', { p_market: league.id })")

    def trades(self, athlete):
        return self.db.select("trades", market_id=f"eq.{self.league}", athlete_id=f"eq.{athlete}", order="at")

    def order(self, phone, athlete, side, kind, shares, limit=None):
        if kind == "market":
            limit = phone.rpc("place_order", p_market=self.league, p_athlete=athlete, p_side=side, p_kind="market",
                              p_shares=shares, p_preview=True)["worst_cents"]
        return phone.rpc("place_order", p_market=self.league, p_athlete=athlete, p_side=side, p_kind=kind,
                         p_shares=shares, p_limit_cents=limit)

    def tradable(self, count):
        """Athletes whose market maker is in right now, whichever day this runs."""
        rows = self.db.select("athletes", season_id=f"eq.{SEASON}", order="fair_value.desc")
        out = []
        for a in rows[10:]:
            book = self.b.rpc("order_book", p_market=self.league, p_athlete=a["id"])
            if not book["market_maker"]["out"]:
                out.append(a)
            if len(out) == count:
                return out
        raise Failed("Fewer tradable athletes than the flows need.")

    def open_athlete(self, ticker):
        self.tab.hash(f"#/athlete/{ticker}")
        self.tab.wait_text("#mm", "Market maker")
        self.tab.wait_text("#book", "Bids")

    # ---- Sign-in

    def signed_in(self):
        return self.tab.eval("typeof user !== 'undefined' && user ? user.email : null")

    def wrong_code(self):
        t = self.tab
        t.allowed += ["auth/v1/verify", "status of 40"]
        t.fill("#code", "000000")
        t.click("#ok")
        t.wait_text("#out .msg", "didn't work")
        check(not t.eval("document.querySelector('#ok').disabled"), "Sign in stays disabled after a wrong code.")
        self.shot("B02", "wrong-code")

    def human_sign_in(self, flow, how):
        t = self.tab
        print(f"\n>>> {self.viewport} window, {flow}: type {how} and press Send code.", flush=True)
        t.wait("!!document.querySelector('#code')", HUMAN_WAIT, "the code screen")
        print(f">>> {self.viewport}: wait for the script's wrong test code to be refused.", flush=True)
        self.wrong_code()
        t.fill("#code", "")
        print(f">>> {self.viewport}: now type the code from the email and press Sign in.", flush=True)
        t.wait("typeof user !== 'undefined' && user", HUMAN_WAIT, "a signed-in player")

    def scripted_code(self, email, kind):
        t = self.tab
        t.before_page(STUB_FETCH % json.dumps({"/auth/v1/otp": {}}))
        t.goto(self.base)
        check("stubs" in t.eval("String(window.fetch)"), "The stub is missing, so a real email would go out.")
        t.requests.clear()
        t.fill("#em", email)
        t.click("#send")
        t.wait_for("#code")
        check(not [r for r in t.requests if "/auth/v1/otp" in r[0]], "A real sign-in email was sent to a fake address.")
        body = {"type": kind, "email": email}
        if kind == "signup":
            body["password"] = secrets.token_urlsafe(24)
        code = online._admin("POST", "admin/generate_link", body)["email_otp"]
        check(re.fullmatch(r"\d{6}", code), f"Supabase's code isn't six digits: {re.sub(r'[0-9]', '9', code)}")
        t.forget_scripts()
        return code

    def b02(self):
        t = self.tab
        if self.signed_in():
            return "already signed in from an earlier run"
        if self.live:
            self.human_sign_in("B02", "your usual email")
            return f"code typed by a person; wrong code refused; signed in as {self.signed_in()}"
        code = self.scripted_code(self.me_email, "magiclink")
        self.shot("B02", "code-screen")
        self.wrong_code()
        t.fill("#code", f"{code[:3]} {code[3:]}")   # pasted with a space, as some mail apps show it
        t.click("#ok")
        t.wait("typeof user !== 'undefined' && user", 15, "a signed-in player")
        t.wait("location.hash === '#/market' || location.hash === '#/leagues'", 10, "the first screen after sign-in")
        self.shot("B02", "signed-in")

    def b03(self):
        t = self.tab
        if self.live:
            if self.signed_in():
                return "already signed in from an earlier run"
            self.human_sign_in("B03", "an address never used here, like yourname+ss3@gmail.com,")
            email = self.signed_in()
            users = online._admin("GET", "admin/users?page=1&per_page=500")["users"]
            made = next(u["created_at"] for u in users if u["email"] == email)
            age = datetime.now(timezone.utc) - datetime.fromisoformat(made[:19] + "+00:00")
            check(age < timedelta(hours=1), f"{email} isn't a new address (made {made}).")
            self.shot("B03", "signed-in")
            return f"new address, real email, code typed by a person: {email}"
        email = f"newbie-{self.stamp}-{self.viewport}@example.com"
        code = self.scripted_code(email, "signup")
        try:
            t.fill("#code", code)
            t.click("#ok")
            t.wait("typeof user !== 'undefined' && user", 15, "the new player signed in")
            t.wait("!!document.querySelector('#view .card, #view h2')", 10, "a first screen")
            self.shot("B03", "new-player")
            check(self.signed_in() == email, "Signed in as someone else.")
            t.hash("#/leagues")
            t.click("#so")
            t.wait_for("#send")
        finally:
            users = online._admin("GET", "admin/users?page=1&per_page=500")["users"]
            for u in users:
                if u["email"] == email:
                    online._admin("DELETE", f"admin/users/{u['id']}")

    # ---- Flows

    def b01(self):
        t = self.tab
        t.requests.clear()
        t.goto(self.base)
        t.wait("document.querySelector('#view').innerText.length > 0", 15, "a first screen")
        bad = [r for r in t.requests if r[1] >= 400]
        check(not bad, f"Failed files: {bad}")
        if t.has("#send"):
            problems = t.eval(LAYOUT % json.dumps(t.vp["mobile"]))
            check(not problems, f"Sign-in layout: {problems}")
        man = t.eval("""(async () => { const l = document.querySelector('link[rel=manifest]'); if (!l) return null;
          const r = await fetch(l.href); return { ok: r.ok, body: await r.json(), url: l.href }; })()""")
        check(man and man["ok"], "No web manifest.")
        icons = [i["src"] for i in man["body"]["icons"]]
        for href in t.eval("[...document.querySelectorAll('link[rel=apple-touch-icon], link[rel=icon]')].map(l => l.getAttribute('href'))"):
            icons.append(href)
        check(len(icons) >= 3, f"Too few icons: {icons}")
        for src in icons:
            st = t.eval(f"fetch({json.dumps(src)}).then(r => [r.status, r.headers.get('content-type')])")
            check(st[0] == 200 and "png" in st[1], f"Icon {src}: {st}")
        note = None
        if self.live:
            check(t.eval("location.protocol") == "https:", "Not HTTPS.")
            plain = urllib.request.urlopen(self.base.replace("https:", "http:"), timeout=30)
            check(plain.geturl().startswith("https:"), "http doesn't move to https.")
            stale = []
            for folder, _, names in os.walk(self.web):
                for n in names:
                    if n == ".DS_Store":
                        continue
                    path = os.path.join(folder, n)
                    url = self.base + os.path.relpath(path, self.web) + f"?check={self.stamp}"
                    with urllib.request.urlopen(url, timeout=30) as r:
                        if r.read() != open(path, "rb").read():
                            stale.append(n)
            check(not stale, f"Live files differ from web/: {stale}")
            note = "HTTPS; http moves to https; every file byte-identical to web/"
        self.shot("B01")
        return note

    def b04(self):
        t = self.tab
        t.hash("#/leagues")
        t.wait_for("#create")
        league_name = f"Flow {self.viewport} {self.stamp}"
        t.fill("#cn", league_name)
        t.fill("#cd", self.name)
        t.set_value("#ce", (today() + timedelta(days=14)).isoformat())
        t.click("#create")
        t.wait_text("#out .msg.ok", "League created")
        self.league = t.wait(f"league && league.name === {json.dumps(league_name)} && league.id", 10, "the new league")
        m = self.db.select("markets", id=f"eq.{self.league}")[0]
        check(m["join_code"] in t.text("#view"), "The join code isn't on the screen.")
        self.b.rpc("join_league", p_code=m["join_code"], p_display_name="Tester B")
        self.shot("B04", "created")
        # The other way in: opening a friend's ?join= link.
        other = self.b.rpc("create_league", p_name=f"Friend's {self.stamp}", p_season=SEASON,
                           p_starts_on=today().isoformat(), p_ends_on=(today() + timedelta(days=14)).isoformat(),
                           p_display_name="Tester B")
        t.goto(f"{self.base}?join={other['join_code']}")
        t.wait(f"document.querySelector('#jc')?.value === {json.dumps(other['join_code'])}", 15, "the code filled in")
        t.fill("#jn", self.name)
        t.click("#join")
        t.wait_text("#out .msg.ok", "Joined")
        check("join=" not in t.eval("location.search"), "The join code stays in the address.")
        t.wait(f"league && league.id === {json.dumps(other['market_id'])}", 10, "the joined league showing")
        self.shot("B04", "joined")
        t.click(f'[data-open="{self.league}"]')
        t.wait(f"league && league.id === {json.dumps(self.league)} && location.hash === '#/market'", 10, "back in the league")
        self.x, self.y = self.tradable(2)
        self.me_id = self.me()

    def b05(self):
        t = self.tab
        t.hash("#/market")
        t.wait_for("a.row")
        rows = self.b.rpc("market_list", p_market=self.league)
        by_id = {a["id"]: a for a in self.db.select("athletes", season_id=f"eq.{SEASON}")}
        traded = [r for r in rows if r["last_cents"] is not None]
        check(traded, "The market list shows no trades although this run made some.")
        for r in traded + rows[:4]:
            a = by_id[r["athlete_id"]]
            line = t.text(f'a.row[href="#/athlete/{a["ticker"]}"]')
            check(line, f"No row for {a['ticker']}.")
            want = {"best bid": r["best_bid_cents"], "best offer": r["best_ask_cents"], "last trade": r["last_cents"]}
            for label, c in want.items():
                if c is not None:
                    check(dollars(c) in line, f"{a['ticker']}: {label} {dollars(c)} isn't in {line!r}")
        self.shot("B05", "list")
        t.fill("#q", self.x["ticker"])
        t.wait("document.querySelectorAll('a.row').length === 1", 5, "search to find one athlete")
        t.fill("#q", "")
        t.click('#pos [data-p="Mine"]')
        t.wait(f"[...document.querySelectorAll('a.row')].some(r => r.getAttribute('href').endsWith('/{self.x['ticker']}'))", 5, "Mine to show a holding")
        t.wait(f"document.querySelectorAll('a.row').length < {len(rows)}", 5, "Mine to filter the list")
        t.click('#pos [data-p="All"]')

    def b06(self):
        t = self.tab
        self.open_athlete(self.x["ticker"])
        t.fill("#n", "5")
        t.wait_text("#pv", "Would cost")
        cost = cents_in(t.text("#pv"))
        self.shot("B06", "preview")
        t.wait("!document.querySelector('#go').disabled", 5, "the Buy button")
        t.click("#go")
        t.wait_text("#out .msg.ok", "Bought 5 of 5")
        check(dollars(cost) in t.text("#out .msg.ok"), f"The fill isn't the preview's {dollars(cost)}.")
        got = [r for r in self.trades(self.x["id"]) if r["buyer_id"] == self.me_id]
        check(sum(r["cents"] for r in got) == cost and sum(r["shares"] for r in got) == 5,
              f"Database trades {got} aren't 5 shares for {cost} cents.")
        self.shot("B06", "filled")

    def b07(self):
        t = self.tab
        self.open_athlete(self.x["ticker"])
        price = round(self.x["fair_value"] * 200)
        t.click('.chip[data-s="sell"]')
        t.click('.chip[data-k="limit"]')
        t.fill("#n", "2")
        t.fill("#lp", f"{price / 100:.2f}")
        t.wait_text("#pv", "Waits in the book")
        t.wait("!document.querySelector('#go').disabled", 5, "the Sell button")
        t.click("#go")
        t.wait_text("#out .msg.ok", "Order placed")
        t.wait_text("#mine", f"Sell 2 at {dollars(price)}")
        t.wait_text("#book", f"{dollars(price)} × 2")
        self.shot("B07", "waiting")
        order = self.db.select("orders", market_id=f"eq.{self.league}", member_id=f"eq.{self.me_id}", status="eq.open")
        check(len(order) == 1, f"Open orders in the database: {order}")
        t.click("#mine [data-c]")
        t.wait_text("#mine", "None.")
        got = self.db.select("orders", id=f"eq.{order[0]['id']}")[0]
        check(got["status"] == "cancelled", f"Order status {got['status']}.")

    def b08(self):
        t = self.tab
        y = self.y
        self.order(self.b, y["id"], "buy", "market", 10)
        self.open_athlete(y["ticker"])
        mm = self.b.rpc("order_book", p_market=self.league, p_athlete=y["id"])["market_maker"]
        price = mm["sells_from_cents"] - 2
        check(price > mm["buys_from_cents"] + 2, "The market maker's spread is too narrow for this flow.")
        t0 = time.time()
        self.order(self.b, y["id"], "sell", "limit", 10, price)
        t.wait_text("#book", f"{dollars(price)} × 10", 10)   # no reload: the page's own check of the book
        seen = time.time() - t0
        self.shot("B08", "their-order")
        t.fill("#n", "4")
        t.wait_text("#pv", dollars(4 * price))
        t.wait("!document.querySelector('#go').disabled", 5, "the Buy button")
        t.click("#go")
        t.wait_text("#out .msg.ok", "Bought 4 of 4")
        t.wait_text("#trades", "Tester B")
        ours = [r for r in self.trades(y["id"]) if r["buyer_id"] == self.me_id]
        check(len(ours) == 1 and ours[0]["cents"] == 4 * price and ours[0]["seller_id"], f"Trade rows: {ours}")
        check(self.b.rpc("order_book", p_market=self.league, p_athlete=y["id"])["last"]["price_cents"] == price,
              "The other player doesn't see the trade.")
        # And the other way: my waiting order filled by them, seen here with no reload.
        mine = price - 1
        t.click('.chip[data-s="sell"]')
        t.click('.chip[data-k="limit"]')
        t.fill("#n", "2")
        t.fill("#lp", f"{mine / 100:.2f}")
        t.wait_text("#pv", "Waits in the book")
        t.wait("!document.querySelector('#go').disabled", 5, "the Sell button")
        t.click("#go")
        t.wait_text("#mine", f"Sell 2 at {dollars(mine)}")
        t0 = time.time()
        self.order(self.b, y["id"], "buy", "market", 2)
        t.wait_text("#mine", "None.", 10)
        t.wait_text("#trades", f"Tester B bought 2 from {self.name}", 3)
        self.shot("B08", "my-order-filled")
        return f"their order on my screen in {seen:.1f}s; my fill seen in {time.time() - t0:.1f}s"

    def b09(self):
        t = self.tab
        t.eval(f"""rpc('place_order', {{ p_market: league.id, p_athlete: {json.dumps(self.x['id'])}, p_side: 'buy', p_kind: 'limit',
                   p_shares: 1, p_limit_cents: 100, p_preview: false }})""")
        t.hash("#/portfolio")
        t.wait_for("#oo")
        a = self.account()
        me = next(r for r in self.b.rpc("leaderboard", p_market=self.league) if r["member_id"] == a["member_id"])
        screen = t.text("#view")
        for label, c in (("net worth", me["net_worth_cents"]), ("cash", a["cash_cents"]),
                         ("set aside", a["set_aside_cents"]), ("free", a["free_cents"])):
            check(dollars(c) in screen, f"Portfolio {label} {dollars(c)} isn't on the screen.")
        check(a["set_aside_cents"] == 100, f"Set aside {a['set_aside_cents']}.")
        all_t =self.db.select("trades", market_id=f"eq.{self.league}")
        paid = self.db.select("dividends", market_id=f"eq.{self.league}", member_id=f"eq.{a['member_id']}")
        start = self.db.select("members", id=f"eq.{a['member_id']}")[0]["starting_cents"]
        cash = start - sum(r["cents"] for r in all_t if r["buyer_id"] == a["member_id"]) + \
            sum(r["cents"] for r in all_t if r["seller_id"] == a["member_id"]) + sum(d["cents"] for d in paid)
        check(cash == a["cash_cents"], f"Cash from trades {cash}, database says {a['cash_cents']}.")
        for h in a["holdings"]:
            check(str(h["shares"]) in t.text("#view table"), f"Holding {h} isn't on the screen.")
        check(self.x["ticker"] in t.text("#oo"), "The open order isn't listed.")
        self.shot("B09")
        t.click("#oo [data-c]")
        t.wait_text("#oo", "None.")

    def b10(self):
        t = self.tab
        t.hash("#/league")
        t.wait_text("#view table", "Tester B")
        board = self.b.rpc("leaderboard", p_market=self.league)
        names = t.eval("[...document.querySelectorAll('#view table a')].map(a => a.innerText.trim())")
        check(names == [r["display_name"] for r in board], f"Leaderboard order {names}.")
        bm = next(r for r in board if r["display_name"] == "Tester B")
        self.shot("B10", "board")
        t.click(f'a[href="#/league/{bm["member_id"]}"]')
        t.wait_text("#view h2", "Tester B")
        held = sum(r["shares"] if r["buyer_id"] == bm["member_id"] else -r["shares"] for r in self.trades(self.y["id"])
                   if bm["member_id"] in (r["buyer_id"], r["seller_id"]))
        t.wait_text("#view", f"{self.y['ticker']}")
        check(f"{held} sh" in t.text("#view"), f"Their {held} shares aren't on the screen.")
        self.shot("B10", "holdings")

    def b11(self):
        t = self.tab
        day = (today() - timedelta(days=30)).isoformat()   # before any real report, so the robot's own never collides
        body = {"day": day, "games": ["AWY at HOM"], "made_at": "2026-10-30T10:00:00Z",
                "players": [{"member_id": self.me_id, "display_name": self.name, "cash_cents": 9000000,
                             "dividend_cents": 12345, "net_worth_cents": 10012345}],
                "overnight_fills": [{"order_id": 1, "display_name": self.name, "side": "buy", "shares": 3,
                                     "ticker": self.x["ticker"], "kind": "limit", "limit_cents": 4500, "cents": 13200}]}
        self.db.insert("reports", [{"market_id": self.league, "day": day, "made_at": body["made_at"], "body": body}],
                       on_conflict="market_id,day", existing="ignore")
        t.hash("#/report")
        t.wait_text("#view", "Filled overnight")
        t.wait_text("#view", f"{self.name}'s buy of 3 {self.x['ticker']} at $45.00 filled at $44.00 overnight")
        check("+$123.45" in t.text("#view"), "The dividend line isn't on the report.")
        self.shot("B11")

    def b12(self):
        t = self.tab
        reason = "ESPN marked a game final with empty stats"
        t.before_page(FAKE_CLOCK % eastern_ms(11, 0))
        t.before_page(STUB_FETCH % json.dumps({"/rest/v1/games": [{"id": "x", "status": "STATUS_FINAL"}],
                                               "/rest/v1/robot_status": [{"stop_reason": reason}]}))
        t.goto(self.base)
        t.wait_text("#banner .warn", reason)
        self.shot("B12", "late")
        t.forget_scripts()
        t.before_page(FAKE_CLOCK % eastern_ms(11, 0))
        t.before_page(STUB_FETCH % json.dumps({"/rest/v1/games": [], "/rest/v1/robot_status": [{"stop_reason": None}]}))
        t.goto(self.base)
        t.wait("typeof user !== 'undefined' && user", 10, "the page to start")
        time.sleep(1.5)
        check(not t.has("#banner .warn"), "A banner shows with no late day.")
        t.forget_scripts()
        t.goto(self.base)
        t.wait("typeof user !== 'undefined' && user && league", 10, "the page to start")

    def b13(self):
        t = self.tab
        t.hash("#/rules")
        t.wait_for(".rules h2")
        self.shot("B13", "rules")
        t.hash("#/portfolio")
        t.wait_for("#oo")
        t.click("a.help")
        t.wait("location.hash === '#/rules/winning' && !!document.getElementById('winning')", 10, "the section")
        time.sleep(0.3)
        spot = t.eval("""(() => { const h = document.querySelector('header').getBoundingClientRect().bottom;
          const r = document.getElementById('winning').getBoundingClientRect(); return { top: r.top, header: h, tall: innerHeight }; })()""")
        check(spot["header"] - 1 <= spot["top"] < spot["tall"] / 2, f"The section lands badly: {spot}")
        self.shot("B13", "section")

    def b14(self):
        t = self.tab
        self.open_athlete(self.x["ticker"])
        t.fill("#n", "1000000")
        t.wait_text("#pv", "Not ordered", 15)
        self.shot("B14", "preview")
        t.wait("!document.querySelector('#go').disabled", 5, "the Buy button")
        t.click("#go")
        t.wait_text("#out .msg.ok", "not ordered", 15)
        said = t.text("#out .msg.ok")
        n = int(re.search(r"Bought (\d+) of 1000000", said).group(1))
        check(0 < n < 1000000, said)
        self.shot("B14", "filled")
        return said

    def b15(self):
        t = self.tab
        t.reload()
        t.wait("typeof user !== 'undefined' && user", 10, "still being signed in after a reload")
        t.hash("#/leagues")
        t.click("#so")
        t.wait_for("#send")
        check(not t.eval("Object.keys(localStorage).some(k => k.includes('auth-token'))"), "The sign-in stayed on the phone.")
        self.shot("B15", "signed-out")

    def b16(self):
        t = self.tab
        mobile = json.dumps(t.vp["mobile"])
        for name, h, ready in (("market", "#/market", "a.row"), ("athlete", f"#/athlete/{self.x['ticker']}", "#trades .small, #trades .dim"),
                               ("portfolio", "#/portfolio", "#oo"), ("league", "#/league", "#view table"),
                               ("report", "#/report", "#view .card"), ("rules", "#/rules", ".rules h2"),
                               ("leagues", "#/leagues", "#create")):
            t.hash(h)
            t.wait_for(ready)
            time.sleep(0.3)
            problems = t.eval(LAYOUT % mobile)
            self.shot("B16", name)
            check(not problems, f"{name}: {problems[:6]}")
            cover = t.eval("""(() => { const v = document.querySelector('#view').getBoundingClientRect(), h = document.querySelector('header').getBoundingClientRect(); return v.top < h.bottom - 1 && scrollY === 0; })()""")
            check(not cover, f"{name}: the header covers the top of the screen.")

    def b17(self):
        t = self.tab
        t.before_page(FAKE_CLOCK % eastern_ms(21, 30))
        t.goto(self.base)
        t.reload()
        check("R(T)" in t.eval("String(Date)"), "The fake clock isn't running.")
        t.hash("#/leagues")
        t.wait_for("#cs")
        got = t.eval("[document.querySelector('#cs').value, document.querySelector('#cs').min]")
        t.forget_scripts()
        want = today().isoformat()
        check(got == [want, want], f"At 9:30 p.m. Eastern the date box says {got}, the database says {want}.")
        t.goto(self.base)
        t.wait("typeof user !== 'undefined' && user", 10, "the page to start")


ORDER = ["B01", "B03", "B02", "B17", "B04", "B06", "B07", "B08", "B05", "B09", "B10", "B11", "B12", "B13", "B14", "B16", "B15"]
SETUP = {"B01", "B02", "B03", "B04"}


def flows_for(target, viewport):
    """Which sign-in runs where: on the public site a person does one kind at each size."""
    skip = {"desktop": {"B03"}, "iphone": {"B02"}}[viewport] if target == "live" else set()
    return [f for f in ORDER if f not in skip]


def run_viewport(args, viewport, base, results):
    live = args.target == "live"
    profile = os.path.expanduser(f"~/.config/sports-stocks/chrome-{viewport}") if live else None
    chrome = Chrome(headless=not (live or args.headed), profile=profile)
    tab = chrome.tab(viewport)
    run = Run(args.target, viewport, base, tab, args.web)
    broken = False
    try:
        for flow in flows_for(args.target, viewport):
            if args.only and flow not in args.only and flow not in SETUP:
                continue
            start = time.time()
            if broken:
                results.append({"target": args.target, "viewport": viewport, "flow": flow, "ok": False, "note": "not run: setup failed"})
                print(f"  {viewport:8} {flow} NOT RUN", flush=True)
                continue
            tab.take_problems()
            try:
                note = getattr(run, flow.lower())()
                problems = tab.take_problems()
                tab.allowed.clear()
                check(not problems, f"Page problems: {problems[:4]}")
                results.append({"target": args.target, "viewport": viewport, "flow": flow, "ok": True,
                                "note": note, "seconds": round(time.time() - start, 1)})
                print(f"  {viewport:8} {flow} pass  {note or ''}", flush=True)
            except Exception as e:  # any failure in a flow is that flow's result; the next one still runs
                run.tab.forget_scripts()
                run.tab.allowed.clear()
                try:
                    run.shot(flow, "FAIL")
                except Failed:
                    pass
                results.append({"target": args.target, "viewport": viewport, "flow": flow, "ok": False,
                                "note": f"{type(e).__name__}: {e}"[:600]})
                print(f"  {viewport:8} {flow} FAIL  {str(e)[:400]}", flush=True)
                if flow == "B04" or (flow == "B02" and not run.signed_in()):
                    broken = True
    finally:
        chrome.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["local", "live"], default="local")
    ap.add_argument("--viewport", choices=["desktop", "iphone", "both"], default="both")
    ap.add_argument("--only", help="comma-separated flows, e.g. B05,B08")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--web", default=WEB, help="folder to serve locally, to prove a flow fails on a broken copy")
    args = ap.parse_args()
    args.only = set(args.only.split(",")) if args.only else None
    server = None
    base = LIVE_URL
    if args.target == "local":
        server = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "--directory", args.web],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{PORT}/"
        time.sleep(0.5)
    results = []
    try:
        for vp in (["desktop", "iphone"] if args.viewport == "both" else [args.viewport]):
            run_viewport(args, vp, base, results)
    finally:
        if server:
            server.terminate()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{args.target}-results.json"), "w") as f:
        json.dump({"finished": datetime.now(timezone.utc).isoformat(), "base": base, "results": results}, f, indent=1)
    bad = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(bad)} of {len(results)} flows passed on {args.target}.")
    sys.exit(min(len(bad), 100))


if __name__ == "__main__":
    main()
