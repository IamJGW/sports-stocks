"""Fair value: starting prices from last season, then the in-season blend and the weekly group re-check.

These are the same formulas as the economy workbook (Settings sheet, "How a starting price is set", and the Live
Rules sheet). tests/test_pricing.py checks that this code and the recalculated workbook agree.
"""
import csv
import re


def group_of(sport, pos):
    if sport == "NFL":
        return {"QB": "NFL QB", "RB": "NFL RB"}.get(pos, "NFL WR/TE")
    if sport == "NHL":
        return "NHL goalies" if pos == "G" else "NHL skaters"
    return "NBA"


def score(line, weights):
    """Fantasy points for one stat line (a season total or a single game)."""
    return sum(float(line.get(k, 0) or 0) * w for k, w in weights.items())


def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def make_tickers(rows, used=None):
    """Short tickers from names (MAHOM, JOKIC); rows in priority order, so the better player gets the plain one."""
    used, out = set(used or ()), {}
    for r in rows:
        name = re.sub(r"\b(Jr|Sr|II|III|IV|V)\.?$", "", r["name"]).strip()
        parts = re.sub(r"[^A-Za-z ]", "", name).upper().split()
        last, first = (parts[-1], parts[0]) if parts else ("X", "X")
        for cand in (last[:5], first[0] + last[:4], first[:2] + last[:3]):
            if cand not in used:
                break
        else:
            n = 2
            while f"{last[:4]}{n}" in used:
                n += 1
            cand = f"{last[:4]}{n}"
        used.add(cand)
        out[r["id"]] = cand
    return out


def sport_groups(econ, sport):
    return {g: v for g, v in econ["groups"].items() if v["sport"] == sport}


def starting_book(rows, econ, sport):
    """List a sport's athletes from last season's totals and set their starting prices.

    Returns {"rate": dividend $ per fantasy point per share, "athletes": [...]} with athletes in rank order. Each has
    id, name, team, pos, group, ppg (last season), leaned (toward the group average), prior_ptg (expected points per
    team game: leaned x repeat), price.
    """
    sp = econ["sports"][sport]
    w, games, weeks = sp["scoring"], sp["games"], sp["weeks"]
    groups = sport_groups(econ, sport)
    people = []
    for r in rows:
        gp = float(r["gp"])
        if gp < 1:
            continue
        people.append({"id": r["id"], "name": r["name"], "team": r["team"], "pos": r["pos"],
                       "group": group_of(sport, r["pos"]), "gp": gp, "ppg": score(r, w) / gp})
    elig = [p for p in people if p["gp"] >= sp["min_games"]]
    # Same rule as the workbook: rank = 1 + how many eligible athletes have more points per game (ties share a rank).
    ppgs = sorted((p["ppg"] for p in elig), reverse=True)
    listed = []
    for p in elig:
        rank = 1 + sum(1 for x in ppgs if x > p["ppg"])
        if rank <= sp["listed"]:
            p["rank"] = rank
            listed.append(p)
    listed.sort(key=lambda p: (p["rank"], p["name"]))
    gavg = {}
    for g in groups:
        vals = [p["ppg"] for p in listed if p["group"] == g]
        gavg[g] = sum(vals) / len(vals) if vals else 0.0
    # Average expected season points of a listed athlete (leaning keeps each group's average).
    avg_exp = sum(gavg[p["group"]] * games * groups[p["group"]]["repeat"] for p in listed) / len(listed)
    rate = econ["target_price"] * econ["weekly_yield"] * weeks / avg_exp
    for p in listed:
        g = groups[p["group"]]
        p["leaned"] = (1 - g["lean"]) * p["ppg"] + g["lean"] * gavg[p["group"]]
        p["prior_ptg"] = p["leaned"] * g["repeat"]
        p["price"] = fair_value(p["prior_ptg"], rate, econ, sport)
    return {"rate": rate, "athletes": listed, "group_avg": gavg}


def fair_value(points_per_team_game, rate, econ, sport):
    """Expected points per team game turned into a price: expected weekly dividend / weekly yield."""
    sp = econ["sports"][sport]
    return points_per_team_game * sp["games"] * rate / sp["weeks"] / econ["weekly_yield"]


def expected_ptg(prior_ptg, multiplier, season_points, team_games, econ):
    """Blend last season's expectation (scaled by the group's re-check multiplier) with this season's points.

    season_points is the sum of his fantasy points in his team's games so far (a missed game adds nothing);
    team_games is how many games his team has played.
    """
    k = econ["live"]["blend_games"]
    return (k * prior_ptg * multiplier + season_points) / (k + team_games)


def recheck(previous, weeks_played, actual, promised, econ):
    """Weekly repeat-factor re-check for one position group.

    actual: the group's listed athletes' fantasy points so far this season (negative games count as zero, like
    dividends). promised: what the prior expected for the same team games (prior_ptg x team games, before any
    multiplier, each team game weighted by its week's promise from the Live Rules sheet). Returns (new multiplier,
    paid vs promised).
    """
    lv = econ["live"]
    if promised <= 0 or weeks_played <= 0:
        return previous, None
    ratio = actual / promised
    k = lv["recheck_weeks"]
    target = (weeks_played * ratio + k) / (weeks_played + k)
    step = lv["recheck_max_move"]
    new = min(max(target, previous * (1 - step)), previous * (1 + step))
    new = min(max(new, lv["recheck_floor"]), lv["recheck_ceiling"])
    return new, ratio
