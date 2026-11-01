"""Shared setup for tests that run against the Supabase TEST project. They are skipped when its keys aren't on this
Mac (python3 tools/set_key.py test, and token for the access token). Nothing here ever touches the live project.

Fixtures, made once and reused:
  - a pretend season 'zz-test' with athletes on teams AAA..FFF, one game each (kickoff moved by the tests);
  - test users tester01..tester24@example.com, made through the admin API with a fresh random password each run.
    Their sign-ins are cached in ~/.config/sports-stocks/test_sessions.json so a run doesn't hit the sign-in limit.
"""
import fcntl
import json
import os
import secrets
import sys
import time
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import online  # noqa: E402
from engine.online import Management, OnlineError, Project, _request  # noqa: E402

PUBLIC = json.load(open(os.path.join(ROOT, "config", "online.json")))
SEASON = "zz-test"
TEAMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
MM = {"spread": 0.04, "lean_per_step": 0.01, "dollars_per_step": 5000}
SESSIONS = os.path.join(online.CONFIG_DIR, "test_sessions.json")

LOCK = os.path.join(online.CONFIG_DIR, "test_run.lock")

_project = _mgmt = _lock = None


def take_turn():
    """One test run at a time on this Mac: the pretend robot days close every league ending before them, and
    reset_season moves the shared pretend season, so two runs at once fail each other in ways that look like bugs.
    Held until this run exits."""
    global _lock
    _lock = open(LOCK, "w")
    fcntl.flock(_lock, fcntl.LOCK_EX)


def project():
    """The test project and its management door, or skip the test."""
    global _project, _mgmt
    if _project is None:
        try:
            _project = Project("test")
            _mgmt = Management(_project.ref)
        except OnlineError as e:
            raise unittest.SkipTest(str(e))
        if _project.ref != urllib.parse.urlparse(PUBLIC["test"]["url"]).hostname.split(".")[0]:
            raise unittest.SkipTest("The test keys don't belong to the test project in config/online.json.")
        take_turn()
    return _project, _mgmt


def sql(query):
    """Raw SQL through the management API, which allows only a few requests a minute: tests use it sparingly."""
    for wait in (5, 10, 20, 40, 0):
        try:
            return project()[1].sql(query)
        except OnlineError as e:
            if not str(e).startswith("429") or not wait:
                raise
            time.sleep(wait)


def lit(v):
    """A SQL literal."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (dict, list)):
        v = json.dumps(v)
    return "'" + str(v).replace("'", "''") + "'"


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def now():
    return datetime.now(timezone.utc)


# ---- The pretend season

def athlete_id(team, n=1):
    return f"{SEASON}:{team}{n}"


def ensure_season():
    """The pretend season, its athletes (fair value $50, 100 shares per step) and one game per team pair, idle."""
    p, _ = project()
    p.insert("seasons", [{"id": SEASON, "sport": "TEST", "season": 2026, "rate": 1.0, "economy": {"market_maker": MM,
              "starting_cash": 100000}}], on_conflict="id", existing="merge")
    rows = []
    for t in TEAMS:
        for n in (1, 2):
            rows.append({"id": athlete_id(t, n), "season_id": SEASON, "espn_id": f"{t}{n}", "ticker": f"{t}{n}",
                         "name": f"Test {t}{n}", "team": t, "pos": "QB", "grp": "TEST", "prior_ppg": 10,
                         "prior_ptg": 10, "start_price": 50, "step_shares": 100, "fair_value": 50.0})
    p.insert("athletes", rows, on_conflict="id", existing="merge")
    later = iso(now() + timedelta(days=30))
    games = [{"id": f"{SEASON}:g{t}", "season_id": SEASON, "espn_id": f"g{t}", "week": 1, "kickoff": later,
              "day": (now() + timedelta(days=30)).date().isoformat(), "home": t, "away": "ZZZ",
              "status": "STATUS_SCHEDULED"} for t in TEAMS]
    p.insert("games", games, on_conflict="id", existing="merge")


def reset_season():
    """Every pretend game a month away and every fair value $50, so the market maker is in."""
    p, _ = project()
    p.update("games", {"kickoff": iso(now() + timedelta(days=30)), "processed_at": None}, season_id=f"eq.{SEASON}")
    p.update("athletes", {"fair_value": 50.0}, season_id=f"eq.{SEASON}")


def kick_off(team):
    """A team's game kicks off now by the database's clock: the market maker steps out of its athletes, and orders
    placed before this moment sleep."""
    sql(f"update public.games set kickoff = now(), processed_at = null where id = {lit(SEASON + ':g' + team)}")


def process(team):
    """The overnight update has processed a team's game: the market maker steps back in."""
    project()[0].update("games", {"processed_at": iso(now())}, id=f"eq.{SEASON}:g{team}")


def set_fair_value(aid, fv):
    project()[0].update("athletes", {"fair_value": fv}, id=f"eq.{aid}")


# ---- Test users (phones)

class Phone:
    """A signed-in test user, calling the database the way the web page will: publishable key plus their token."""

    def __init__(self, n, user_id, token):
        self.n, self.user_id, self.token = n, user_id, token

    def _headers(self):
        h = {"apikey": PUBLIC["test"]["publishable_key"]}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def rpc(self, name, **args):
        return _request("POST", f"{PUBLIC['test']['url']}/rest/v1/rpc/{name}", self._headers(), args)[1]

    def select(self, table, **filters):
        q = urllib.parse.urlencode({"select": "*", **filters})
        return _request("GET", f"{PUBLIC['test']['url']}/rest/v1/{table}?{q}", self._headers())[1]

    def request(self, method, path, body=None, headers=None):
        return _request(method, f"{PUBLIC['test']['url']}/rest/v1/{path}", {**self._headers(), **(headers or {})},
                        body)[1]


def _admin(method, path, body=None):
    p, _ = project()
    return _request(method, f"{p.url}/auth/v1/{path}", p._headers(), body)[1]


def _load_sessions():
    try:
        with open(SESSIONS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_sessions(s):
    fd = os.open(SESSIONS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(s, f)


_phones = {}


def phones(count):
    """count signed-in test users (tester01, tester02, ...)."""
    project()
    if len(_phones) >= count:
        return [_phones[i] for i in range(1, count + 1)]
    cache = _load_sessions()
    users = None
    for n in range(1, count + 1):
        if n in _phones:
            continue
        email = f"tester{n:02d}@example.com"
        s = cache.get(email)
        if s and s["expires_at"] > time.time() + 600:
            _phones[n] = Phone(n, s["user_id"], s["token"])
            continue
        if users is None:
            got = _admin("GET", "admin/users?page=1&per_page=200")
            users = {u["email"]: u["id"] for u in got["users"]}
        password = secrets.token_urlsafe(24)
        if email in users:
            _admin("PUT", f"admin/users/{users[email]}", {"password": password})
        else:
            users[email] = _admin("POST", "admin/users", {"email": email, "password": password,
                                                          "email_confirm": True})["id"]
        got = _request("POST", f"{PUBLIC['test']['url']}/auth/v1/token?grant_type=password",
                       {"apikey": PUBLIC["test"]["publishable_key"]}, {"email": email, "password": password})[1]
        cache[email] = {"user_id": got["user"]["id"], "token": got["access_token"],
                        "expires_at": time.time() + got["expires_in"]}
        _phones[n] = Phone(n, got["user"]["id"], got["access_token"])
    _save_sessions(cache)
    return [_phones[i] for i in range(1, count + 1)]


def anonymous():
    """A phone that isn't signed in: the publishable key alone."""
    return Phone(0, None, None)
