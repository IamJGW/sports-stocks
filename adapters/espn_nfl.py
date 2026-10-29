"""ESPN's public NFL feed: the only file that knows what it looks like.

It turns ESPN's schedule and box scores into plain records the rest of the game uses:
    game:      {"id", "week", "kickoff" (UTC ISO), "home", "away", "final"}
    stat line: {"athlete_id", "name", "team", "pass_yd", "pass_td", "int", "rush_yd", "rush_td", "rec", "rec_yd",
                "rec_td", "two_pt", "ret_td", "fum_lost"}
The feed is public but unofficial. If ESPN changes it, fix it here.

Downloads are cached in data/espn_nfl_2026/: finished games are kept for good (gzipped), schedules for unfinished
weeks are fetched again each time.
"""
import gzip
import json
import os
import re
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "espn_nfl_2026")
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
SEASON = 2026
STAT_KEYS = ("pass_yd", "pass_td", "int", "rush_yd", "rush_td", "rec", "rec_yd", "rec_td", "two_pt", "ret_td",
             "fum_lost")


class FeedError(Exception):
    """The feed returned something we can't trust. Nothing should be paid from it."""


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Sports Stocks prototype)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # network hiccup: wait and retry, then give up loudly
            if attempt == 2:
                raise FeedError(f"Could not download {url}: {e}")
            time.sleep(2 + attempt * 3)


def _cache_path(name):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, name)


def _read_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _write_gz(path, data):
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


# ---- Schedule

def week_schedule(week, offline=False):
    """Games of one regular-season week. Uses the cached copy when every game in it is final (or when offline)."""
    path = _cache_path(f"schedule_week{week:02d}.json.gz")
    if os.path.exists(path):
        cached = parse_schedule(_read_gz(path), week)
        if offline or all(g["final"] for g in cached):
            return cached
    if offline:
        raise FeedError(f"No saved schedule for week {week} and offline mode is on.")
    raw = _get(f"{SITE}/scoreboard?dates={SEASON}&seasontype=2&week={week}")
    games = parse_schedule(raw, week)
    _write_gz(path, raw)
    return games


def parse_schedule(raw, week):
    if raw.get("season", {}).get("year") != SEASON or raw.get("week", {}).get("number") != week:
        raise FeedError(f"Schedule for week {week} came back for a different season or week.")
    games = []
    for e in raw.get("events", []):
        comp = e["competitions"][0]
        side = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
        status = e["status"]["type"]
        games.append({"id": e["id"], "week": week, "kickoff": e["date"], "home": side["home"], "away": side["away"],
                      "final": bool(status.get("completed")) and status.get("name") == "STATUS_FINAL",
                      "status": status.get("name")})
    return games


# ---- Box scores

def has_player_stats(raw):
    """True when both teams have passing, rushing and receiving sections. Right after a game ESPN sometimes marks it
    final while the player stats are still empty (DAL at PHI, week 7 2026); such a copy must not be kept for good."""
    teams = raw.get("boxscore", {}).get("players", [])
    return len(teams) == 2 and all({"passing", "rushing", "receiving"} <= {s.get("name") for s in t.get("statistics", [])}
                                   for t in teams)


def game_summary(game_id, offline=False):
    """The raw box score of a finished game, downloaded once and then read from the cache.

    A saved copy without player stats is downloaded again (unless offline), so an early empty copy can't block the
    nightly job for good."""
    path = _cache_path(f"game_{game_id}.json.gz")
    if os.path.exists(path):
        raw = _read_gz(path)
        if offline or has_player_stats(raw):
            return raw
    if offline:
        raise FeedError(f"No saved box score for game {game_id} and offline mode is on.")
    raw = _get(f"{SITE}/summary?event={game_id}")
    status = raw.get("header", {}).get("competitions", [{}])[0].get("status", {}).get("type", {})
    if status.get("name") != "STATUS_FINAL":
        raise FeedError(f"Game {game_id} is not final yet ({status.get('name')}).")
    if not has_player_stats(raw):
        raise FeedError(f"Game {game_id} is final but ESPN has no player stats for it yet; trying again next run.")
    _write_gz(path, raw)
    return raw


def _num(text):
    text = str(text).strip()
    if text in ("", "--", "-"):
        return 0
    return int(float(text))


# Two-point conversions only appear in the scoring-play text, e.g.
#   "... (Drake Maye Pass to Hunter Henry for Two-Point Conversion)"  or  "(Kyren Williams Run for Two-Point Conversion)"
TWO_PT_PASS = re.compile(r"\(([^()]+?) Pass to ([^()]+?) for Two-Point Conversion\)", re.I)
TWO_PT_RUN = re.compile(r"\(([^()]+?) (?:Run|Rush) for Two-Point Conversion\)", re.I)


def _name_key(name):
    name = re.sub(r"\b(Jr|Sr|II|III|IV|V)\.?$", "", name.strip())
    return re.sub(r"[^a-z]", "", name.lower())


def parse_game(raw):
    """Stat lines for every QB/RB/WR/TE-type athlete in a box score, plus the checks that the numbers add up.

    Returns {"game_id", "kickoff", "final", "teams": [abbr, abbr], "lines": {athlete_id: line}, "problems": [...]}.
    """
    comp = raw["header"]["competitions"][0]
    game_id = raw["header"]["id"]
    final = comp["status"]["type"]["name"] == "STATUS_FINAL"
    teams = [c["team"]["abbreviation"] for c in comp["competitors"]]
    lines, problems, names = {}, [], {}

    def line(team, ath):
        aid = str(ath["id"])
        if aid not in lines:
            lines[aid] = {"athlete_id": aid, "name": ath["displayName"], "team": team, **{k: 0 for k in STAT_KEYS}}
            names[(team, _name_key(ath["displayName"]))] = aid
        return lines[aid]

    for tm in raw["boxscore"]["players"]:
        team = tm["team"]["abbreviation"]
        cats = {c["name"]: c for c in tm["statistics"]}
        for need in ("passing", "rushing", "receiving"):
            if need not in cats:
                problems.append(f"{team}: no {need} section in the box score")

        def add(cat, mapping):
            c = cats.get(cat)
            if not c:
                return
            idx = {k: i for i, k in enumerate(c["keys"])}
            for a in c["athletes"]:
                ln = line(team, a["athlete"])
                for key, stat in mapping.items():
                    ln[stat] += _num(a["stats"][idx[key]])
            # The athletes' rows must add up to the team total for each counted stat.
            if c.get("totals"):
                for key, stat in mapping.items():
                    if cat == "passing" and key == "passingYards":
                        continue  # the team total is net of sacks; checked against receiving below
                    total = _num(c["totals"][idx[key]])
                    summed = sum(_num(a["stats"][idx[key]]) for a in c["athletes"])
                    if total != summed:
                        problems.append(f"{team} {cat} {key}: athletes add to {summed}, team total says {total}")

        add("passing", {"passingYards": "pass_yd", "passingTouchdowns": "pass_td", "interceptions": "int"})
        add("rushing", {"rushingYards": "rush_yd", "rushingTouchdowns": "rush_td"})
        add("receiving", {"receptions": "rec", "receivingYards": "rec_yd", "receivingTouchdowns": "rec_td"})
        add("fumbles", {"fumblesLost": "fum_lost"})
        add("kickReturns", {"kickReturnTouchdowns": "ret_td"})
        add("puntReturns", {"puntReturnTouchdowns": "ret_td"})

        # Every yard thrown is a yard caught.
        if "passing" in cats and "receiving" in cats:
            p, r = cats["passing"], cats["receiving"]
            py = sum(_num(a["stats"][p["keys"].index("passingYards")]) for a in p["athletes"])
            ry = sum(_num(a["stats"][r["keys"].index("receivingYards")]) for a in r["athletes"])
            if py != ry:
                problems.append(f"{team}: passers threw for {py} yards but receivers caught {ry}")

    for play in raw.get("scoringPlays", []):
        text = play.get("text", "")
        team = play.get("team", {}).get("abbreviation")
        found = [m.group(1) for m in TWO_PT_RUN.finditer(text)]
        for m in TWO_PT_PASS.finditer(text):
            found += [m.group(1), m.group(2)]
        if "two-point conversion" in text.lower() and "fail" not in text.lower() and not found:
            problems.append(f"Couldn't read a two-point conversion: {text!r}")
        for name in found:
            aid = names.get((team, _name_key(name)))
            if aid:
                lines[aid]["two_pt"] += 1
            # A non-skill-position player (a holder, say) may not have a stat line; nothing listed to pay then.

    for aid, ln in lines.items():
        for k in STAT_KEYS:
            if k in ("pass_yd", "rush_yd", "rec_yd"):
                if not -100 <= ln[k] <= 700:
                    problems.append(f"{ln['name']}: {k} = {ln[k]} looks wrong")
            elif not 0 <= ln[k] <= 30:
                problems.append(f"{ln['name']}: {k} = {ln[k]} looks wrong")

    return {"game_id": game_id, "kickoff": comp["date"], "final": final, "teams": teams, "lines": lines,
            "problems": problems}


def fresh_game_summary(game_id):
    """Download a game's box score again, ignoring the saved copy (to spot stat corrections). Not saved."""
    return _get(f"{SITE}/summary?event={game_id}")
