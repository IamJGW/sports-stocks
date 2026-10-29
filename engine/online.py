"""Talking to Supabase with the standard library only (Python has no Postgres driver built in).

Two doors:
  - the project's web API (PostgREST): read tables, insert rows, call database functions. Uses the project's secret
    key, so it is for the robot and tools only, never the web page.
  - Supabase's management API: run raw SQL, for database changes (tools/db.py). Uses the personal access token.

Keys come from environment variables (GitHub Actions) or ~/.config/sports-stocks/<target>.env (tools/set_key.py).
Nothing here prints a key.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

CONFIG_DIR = os.path.expanduser("~/.config/sports-stocks")
MANAGEMENT = "https://api.supabase.com/v1"
AGENT = "sports-stocks-tools/1"  # Supabase's gateway refuses Python's default user agent
PAGE = 1000  # the web API returns at most this many rows per request


class OnlineError(Exception):
    """Supabase refused a request. The message is the reason it gave."""


def _read_env(name):
    path = os.path.join(CONFIG_DIR, f"{name}.env")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path) as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                out[k] = v
    return out


def _request(method, url, headers, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": AGENT, "Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode()
            return r.headers, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        try:
            msg = json.loads(text)
            msg = msg.get("message") or msg.get("msg") or msg.get("error") or text
        except ValueError:
            msg = text
        raise OnlineError(f"{e.code}: {msg}") from None


class Project:
    """One Supabase project, reached with its secret key."""

    def __init__(self, target):
        self.target = target
        env = _read_env(target)
        prefix = "" if target == "live" else f"{target.upper()}_"
        self.url = os.environ.get(f"{prefix}SUPABASE_URL") or env.get("SUPABASE_URL")
        self.key = os.environ.get(f"{prefix}SUPABASE_SECRET_KEY") or env.get("SUPABASE_SECRET_KEY")
        if not (self.url and self.key):
            raise OnlineError(f"No keys for the '{target}' project. Run: python3 tools/set_key.py {target}")
        self.ref = urllib.parse.urlparse(self.url).hostname.split(".")[0]

    def _headers(self, extra=None):
        h = {"apikey": self.key}
        if not self.key.startswith("sb_"):  # an older service_role key is a JWT and also goes as the bearer
            h["Authorization"] = f"Bearer {self.key}"
        return {**h, **(extra or {})}

    def rpc(self, name, **args):
        """Call a database function; returns what it returns."""
        return _request("POST", f"{self.url}/rest/v1/rpc/{name}", self._headers(), args)[1]

    def select(self, table, **filters):
        """Every row of a table, e.g. select('games', processed_at='is.null', order='kickoff'). Pages through."""
        rows, offset = [], 0
        while True:
            q = {"select": "*", **filters, "limit": PAGE, "offset": offset}
            got = _request("GET", f"{self.url}/rest/v1/{table}?{urllib.parse.urlencode(q)}", self._headers())[1]
            rows += got
            if len(got) < PAGE:
                return rows
            offset += PAGE

    def insert(self, table, rows, on_conflict=None, existing="error"):
        """Insert rows in batches. existing: 'error', 'ignore' (keep the stored row) or 'merge' (overwrite it)."""
        prefer = ["return=minimal"]
        if existing == "ignore":
            prefer.append("resolution=ignore-duplicates")
        elif existing == "merge":
            prefer.append("resolution=merge-duplicates")
        url = f"{self.url}/rest/v1/{table}"
        if on_conflict:
            url += f"?on_conflict={on_conflict}"
        for i in range(0, len(rows), PAGE):
            _request("POST", url, self._headers({"Prefer": ",".join(prefer)}), rows[i:i + PAGE])


class Management:
    """Raw SQL on a project, through Supabase's management API and the personal access token."""

    def __init__(self, project_ref):
        self.ref = project_ref
        self.token = os.environ.get("SUPABASE_ACCESS_TOKEN") or _read_env("token").get("SUPABASE_ACCESS_TOKEN")
        if not self.token:
            raise OnlineError("No access token. Run: python3 tools/set_key.py token")

    def sql(self, query):
        """Run SQL; returns the last statement's rows as a list of dicts."""
        return _request("POST", f"{MANAGEMENT}/projects/{self.ref}/database/query",
                        {"Authorization": f"Bearer {self.token}"}, {"query": query})[1]
