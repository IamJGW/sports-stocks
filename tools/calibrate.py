"""Work out each position group's 'lean toward average' and 'repeat factor' from one pair of seasons, and check them
on the next pair. Usage (from sports-exchange/):  python3 tools/calibrate.py

Calibrate: priced on 2023 (NFL) / 2023-24 (NBA, NHL), paid on the season after.
Test:      priced on 2024 / 2024-25, paid on 2025 / 2025-26 (the seasons in the workbook).

Lean toward average: within a group, how much of an athlete's gap from the group average carries into next season.
  If next season's points per game = a + b * this season's, the lean is 1 - b.
Repeat factor: across a group, actual next-season points / (leaned points per game x games per team). It folds in
  games missed and the group's overall drop-off, so a group that tends to fall back (goalies) is priced lower.
"""
import csv
import statistics as st
import sys

sys.path.insert(0, "tools")
from build_economy_workbook import GROUPS, SPORTS, group_of  # noqa: E402

FILES = {"NFL": (2023, 2024, 2025), "NBA": (2024, 2025, 2026), "NHL": (2024, 2025, 2026)}


def load(path):
    with open(path) as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def fp(r, sp):
    return sum(float(r[k]) * w for k, _, w in sp["stats"])


def listed(prior, sp):
    elig = [r for r in prior.values() if float(r["gp"]) >= sp["min_gp"]]
    elig.sort(key=lambda r: -fp(r, sp) / float(r["gp"]))
    return elig[:sp["listed"]]


def pairs(sp, a, b):
    prior = load(f"data/{sp['key'].lower()}_{a}.csv")
    nxt = load(f"data/{sp['key'].lower()}_{b}.csv")
    out = []
    for r in listed(prior, sp):
        n = nxt.get(r["id"])
        out.append({"group": group_of(sp["key"], r["pos"]), "fpg": fp(r, sp) / float(r["gp"]),
                    "fp_next": fp(n, sp) if n else 0.0, "gp_next": float(n["gp"]) if n else 0.0})
    return out


def calibrate(sp, rows):
    factors = {}
    for g in [g for g, s, *_ in GROUPS if s == sp["key"]]:
        rs = [r for r in rows if r["group"] == g]
        avg = st.mean(r["fpg"] for r in rs)
        played = [r for r in rs if r["gp_next"] > 0]
        x = [r["fpg"] for r in played]
        y = [r["fp_next"] / r["gp_next"] for r in played]
        mx, my = st.mean(x), st.mean(y)
        slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sum((a - mx) ** 2 for a in x)
        lean = min(1.0, max(0.0, 1 - slope))
        leaned = [(1 - lean) * r["fpg"] + lean * avg for r in rs]
        repeat = sum(r["fp_next"] for r in rs) / (sum(leaned) * sp["games"])
        factors[g] = (lean, repeat, avg, len(rs))
    return factors


def evaluate(sp, rows, factors):
    """Equal dollars in every listed athlete: weekly dividend return as a share of the target, per group and sport."""
    exp = {}
    for r in rows:
        lean, repeat, _, _ = factors[r["group"]]
        avg = st.mean(x["fpg"] for x in rows if x["group"] == r["group"])  # group average in the pricing season
        r["exp"] = ((1 - lean) * r["fpg"] + lean * avg) * sp["games"] * repeat
    mean_exp = st.mean(r["exp"] for r in rows)
    # price / target = exp / mean_exp; season return / (yield * weeks) = fp_next / mean_exp ... per athlete:
    for r in rows:
        r["ratio"] = max(0.0, r["fp_next"]) / r["exp"]  # realised / promised dividends
    by = {}
    for r in rows:
        by.setdefault(r["group"], []).append(r["ratio"])
    return st.mean(r["ratio"] for r in rows), {g: (st.mean(v), len(v)) for g, v in by.items()}


def main():
    """Calibrate each way round, test on the other pair, and print the averaged factors the workbook uses."""
    for sp in SPORTS:
        a, b, c = FILES[sp["key"]]
        early, late = pairs(sp, a, b), pairs(sp, b, c)
        fac_early, fac_late = calibrate(sp, early), calibrate(sp, late)
        for label, fac, test in (("set on older pair, tested on newer", fac_early, late),
                                 ("set on newer pair, tested on older", fac_late, early)):
            sport, groups = evaluate(sp, [dict(r) for r in test], fac)
            gtxt = ", ".join(f"{g} {m:.0%}" for g, (m, n) in groups.items())
            print(f"{sp['key']} {label}: {sport:.0%} of promised dividends | {gtxt}")
        for g in fac_early:
            lean = (fac_early[g][0] + fac_late[g][0]) / 2
            repeat = (fac_early[g][1] + fac_late[g][1]) / 2
            print(f"  workbook default {g:12s} lean {lean:.2f}  repeat {repeat:.2f}")


if __name__ == "__main__":
    main()
