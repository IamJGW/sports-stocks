"""Fetch one regular season of player totals from ESPN's public stats feed and save a CSV per sport.

Usage (from sports-exchange/):  python3 tools/fetch_season_stats.py [seasons back, default 0]
With no argument, writes data/nfl_2025.csv, data/nba_2026.csv, data/nhl_2026.csv; with 1, the season before
(nfl_2024, nba_2025, nhl_2025). Standard library only.

The feed is public but unofficial: if ESPN changes it, this script is the one place to fix.
ESPN names NBA and NHL seasons by the year they end, so 2026 means 2025-26.
"""
import csv
import json
import os
import sys
import time
import urllib.request

BASE = "https://site.web.api.espn.com/apis/common/v3/sports/{path}/statistics/byathlete"

SPORTS = {
    "nfl": {
        "path": "football/nfl", "season": 2025,
        # The NFL list only includes "qualified" players for whatever stat it is sorted by, so take the union of three.
        "sorts": ["passing.passingYards:desc", "rushing.rushingYards:desc", "receiving.receivingYards:desc"],
        "positions": {"QB", "RB", "WR", "TE"},
        "columns": {
            "gp": ("general", "gamesPlayed"),
            "pass_yd": ("passing", "passingYards"), "pass_td": ("passing", "passingTouchdowns"),
            "int": ("passing", "interceptions"),
            "rush_yd": ("rushing", "rushingYards"), "rush_td": ("rushing", "rushingTouchdowns"),
            "rec": ("receiving", "receptions"), "rec_yd": ("receiving", "receivingYards"),
            "rec_td": ("receiving", "receivingTouchdowns"),
            "fum_lost_rush": ("rushing", "rushingFumblesLost"), "fum_lost_rec": ("receiving", "receivingFumblesLost"),
            "two_pt": ("scoring", "totalTwoPointConvs"), "ret_td": ("scoring", "returnTouchdowns"),
        },
    },
    "nba": {
        "path": "basketball/nba", "season": 2026, "sorts": [None], "positions": None,
        "columns": {
            "gp": ("general", "gamesPlayed"), "min": ("general", "minutes"),
            "pts": ("offensive", "points"), "reb": ("general", "rebounds"), "ast": ("offensive", "assists"),
            "stl": ("defensive", "steals"), "blk": ("defensive", "blocks"), "tov": ("offensive", "turnovers"),
            "fg3m": ("offensive", "threePointFieldGoalsMade"),
            "dbl_dbl": ("general", "doubleDouble"), "tpl_dbl": ("general", "tripleDouble"),
        },
    },
    "nhl": {
        "path": "hockey/nhl", "season": 2026, "sorts": [None], "positions": None,
        "columns": {
            "gp": ("general", "games"),
            "goals": ("offensive", "goals"), "assists": ("offensive", "assists"),
            "ppg": ("offensive", "powerPlayGoals"), "ppa": ("offensive", "powerPlayAssists"),
            "shots": ("offensive", "shotsTotal"),
            "wins": ("general", "wins"), "goals_against": ("defensive", "goalsAgainst"),
            "saves": ("defensive", "saves"), "shutouts": ("defensive", "shutouts"),
        },
    },
}


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def number(text):
    if text in (None, "", "-"):
        return 0
    text = str(text).replace(",", "")
    return float(text) if "." in text else int(text)


def fetch_sport(key, cfg):
    players = {}
    for sort in cfg["sorts"]:
        page = 1
        while True:
            url = f"{BASE.format(path=cfg['path'])}?season={cfg['season']}&seasontype=2&limit=500&page={page}"
            if sort:
                url += f"&sort={sort}"
            data = get_json(url)
            names = {c["name"]: c["names"] for c in data["categories"]}
            for row in data.get("athletes", []):
                ath = row["athlete"]
                pos = ath.get("position", {}).get("abbreviation", "")
                if cfg["positions"] and pos not in cfg["positions"]:
                    continue
                totals = {c["name"]: c.get("totals") or [] for c in row["categories"]}
                rec = {"id": ath["id"], "name": ath["displayName"], "team": ath.get("teamShortName", ""), "pos": pos}
                for col, (cat, stat) in cfg["columns"].items():
                    vals = totals.get(cat, [])
                    idx = names.get(cat, []).index(stat) if stat in names.get(cat, []) else None
                    rec[col] = number(vals[idx]) if idx is not None and idx < len(vals) else 0
                players[ath["id"]] = rec
            pages = data["pagination"]["pages"]
            print(f"  {key} sort={sort} page {page}/{pages}: {len(players)} players so far")
            if page >= pages:
                break
            page += 1
            time.sleep(0.5)
    return list(players.values())


def main():
    back = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    os.makedirs("data", exist_ok=True)
    for key, cfg in SPORTS.items():
        cfg = dict(cfg, season=cfg["season"] - back)
        rows = fetch_sport(key, cfg)
        if key == "nfl":
            for r in rows:
                r["fum_lost"] = r.pop("fum_lost_rush") + r.pop("fum_lost_rec")
        path = f"data/{key}_{cfg['season']}.csv"
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {path}: {len(rows)} players")




def fill_missing_nfl(prior_season, season, scoring, min_games=6, top=200):
    """The NFL season list skips players who weren't 'qualified' (often injured), which would wrongly count them as
    scoring nothing. Look up each of the prior season's top players who is absent, one athlete at a time.
    Usage: python3 tools/fetch_season_stats.py fill-nfl 2024 2025"""
    def load(path):
        with open(path) as f:
            return list(csv.DictReader(f))
    prior, current = load(f"data/nfl_{prior_season}.csv"), load(f"data/nfl_{season}.csv")
    have = {r["id"] for r in current}
    def fpg(r):
        return sum(float(r[k]) * w for k, w in scoring.items()) / float(r["gp"])
    pool = sorted((r for r in prior if float(r["gp"]) >= min_games), key=fpg, reverse=True)[:top]
    cols = SPORTS["nfl"]["columns"]
    added = []
    for p in pool:
        if p["id"] in have:
            continue
        url = f"https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{p['id']}/stats?seasontype=2"
        data = get_json(url)
        rec = {"id": p["id"], "name": p["name"], "team": "", "pos": p["pos"]}
        for col, (cat, stat) in cols.items():
            rec[col] = 0
            for c in data.get("categories", []):
                names = c.get("names") or []
                if stat not in names:
                    continue
                for s in c.get("statistics", []):
                    if s.get("season", {}).get("year") == season:
                        rec[col] = max(rec[col], number(s["stats"][names.index(stat)]))
                        rec["team"] = rec["team"] or s.get("teamSlug", "")
        rec["fum_lost"] = rec.pop("fum_lost_rush") + rec.pop("fum_lost_rec")
        current.append(rec)
        added.append(f"{p['name']} ({rec['gp']} gp)")
        time.sleep(0.3)
    with open(f"data/nfl_{season}.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(current[0].keys()))
        writer.writeheader()
        writer.writerows(current)
    print(f"added {len(added)} players to data/nfl_{season}.csv: " + ", ".join(added))


NFL_HALF_PPR = dict(pass_yd=.04, pass_td=4, int=-2, rush_yd=.1, rush_td=6, rec=.5, rec_yd=.1, rec_td=6, two_pt=2,
                    ret_td=6, fum_lost=-2)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fill-nfl":
        fill_missing_nfl(int(sys.argv[2]), int(sys.argv[3]), NFL_HALF_PPR)
    else:
        main()
