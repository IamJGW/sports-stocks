"""Fit an availability curve on 2025 and test it: on 2026 weeks 1-6 (never used in the fit) and by replaying the
re-check and fair values. Run from sports-exchange/:  python3 research/curve.py
"""
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from availability import ECON, GROUPS, by_week, load_2025, load_2026  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import pricing  # noqa: E402

LV = ECON["live"]


def fit_share(rows, last_regular=17):
    """Played share by week as plateau + (start - plateau) * exp(-(week - 1) / tau), weeks 1..last_regular,
    least squares weighted by team games. Returns (start, plateau, tau, fitted share function)."""
    wk = by_week(rows)
    pts = [(w, ap / n, n) for w, (_, _, n, ap) in wk.items() if w <= last_regular]
    best = None
    for i in range(5, 161):
        tau = i / 20
        xs = [(math.exp(-(w - 1) / tau), s, n) for w, s, n in pts]
        # s = c + d * x  (c = plateau, d = start - plateau)
        sw = sum(n for _, _, n in xs)
        mx = sum(x * n for x, _, n in xs) / sw
        my = sum(s * n for _, s, n in xs) / sw
        d = sum(n * (x - mx) * (s - my) for x, s, n in xs) / sum(n * (x - mx) ** 2 for x, _, n in xs)
        c = my - d * mx
        err = sum(n * (c + d * x - s) ** 2 for x, s, n in xs)
        if best is None or err < best[0]:
            best = (err, c + d, c, tau)
    _, start, plateau, tau = best
    return start, plateau, tau, (lambda w: plateau + (start - plateau) * math.exp(-(w - 1) / tau))


def make_curve(share, week18, games_per_week):
    """Promise multiplier by week, scaled so its average over the season's team games is exactly 1 (the repeat
    factor still sets the season total; the curve only moves it between weeks)."""
    raw = {w: (share(w) if w < 18 else week18) for w in range(1, 19)}
    total = sum(raw[w] * games_per_week.get(w, 0) for w in raw)
    n = sum(games_per_week.values())
    return {w: raw[w] * n / total for w in raw}


def recheck_path(rows, curve, weeks):
    """Replay the weekly re-check. curve=None is today's flat promise. Returns {group: [(week, ratio, mult)]}."""
    out = {}
    for g in GROUPS:
        mult, path, act, prom = 1.0, [], 0.0, 0.0
        wk = by_week(rows, g)
        for w in weeks:
            if w not in wk:
                continue
            act += wk[w][0]
            prom += wk[w][1] * (curve[w] if curve else 1.0)
            mult, ratio = pricing.recheck(mult, w, act, prom, ECON)
            path.append((w, ratio, mult))
        out[g] = path
    return out


def fair_values(rows, athletes, curve, mults, through, sched_weeks, rate):
    """Each athlete's fair value after `through` weeks. Flat (curve=None): today's rule. Curve: the season so far is
    measured against the curve (points / sum of curve over his team games) and the price looks ahead at the average
    curve value of the weeks still to come."""
    k = LV["blend_games"]
    pts, units = defaultdict(float), defaultdict(float)
    for r in rows:
        if r["week"] <= through:
            pts[r["id"]] += r["points"]
            units[r["id"]] += curve[r["week"]] if curve else 1.0
    ahead = 1.0
    if curve:
        rest = [w for w in sched_weeks if w > through]
        ahead = sum(curve[w] * sched_weeks[w] for w in rest) / sum(sched_weeks[w] for w in rest)
    out = {}
    for a in athletes:
        ptg = (k * a["prior_ptg"] * mults[a["group"]] + pts[a["id"]]) / (k + units[a["id"]]) * ahead
        out[a["id"]] = pricing.fair_value(ptg, rate, ECON, "NFL")
    return out


def main():
    ath25, rows25, _ = load_2025()
    ath26, rows26 = load_2026()
    gpw25 = {w: v[2] for w, v in by_week(rows25).items()}

    start, plateau, tau, share = fit_share(rows25)
    wk25 = by_week(rows25)
    pr18 = wk25[18][0] / wk25[18][1]
    season_ratio = sum(v[0] for v in wk25.values()) / sum(v[1] for v in wk25.values())
    # Week 18 (resting starters, eliminated teams): set from what week 18 paid against the season, in share units.
    week18 = pr18 / season_ratio * (sum(v[3] for v in wk25.values()) / sum(v[2] for v in wk25.values()))
    print(f"Fitted on 2025 (weeks 1-17): played share starts {start:.1%}, settles at {plateau:.1%}, "
          f"time constant {tau:.1f} weeks; week 18 set to {week18:.1%} (points-based)")
    curve = make_curve(share, week18, gpw25)
    print("Curve (promise by week, average 1 over 2025's team games):")
    print("  " + "  ".join(f"w{w} {curve[w]:.2f}" for w in range(1, 19)))

    print("\nOut of sample, mechanism: 2026 played share vs the 2025 curve's prediction")
    wk26 = by_week(rows26)
    for w, (_, _, n, ap) in wk26.items():
        print(f"  week {w}: 2026 {ap / n:5.1%}   2025 fit {share(w):5.1%}   2025 actual "
              f"{wk25[w][3] / wk25[w][2]:5.1%}  (n={n})")

    print("\nBy group, 2025 played share weeks 1-3 / 4-6 / 7-16 / 17 / 18 (does one curve fit all groups?)")
    for g in GROUPS:
        wk = by_week(rows25, g)
        def sh(ws):
            return sum(wk[w][3] for w in ws) / sum(wk[w][2] for w in ws)
        print(f"  {g:10} {sh(range(1, 4)):5.1%} {sh(range(4, 7)):5.1%} {sh(range(7, 17)):5.1%} {sh([17]):5.1%} "
              f"{sh([18]):5.1%}")

    # Points, flat vs curve, cumulative by week.
    for label, rows, wks in (("2025 (curve fitted here: in sample)", rows25, range(1, 19)),
                             ("2026 weeks 1-6 (out of sample)", rows26, range(1, 7))):
        print(f"\n{label}: cumulative paid / promised, flat -> curve")
        for g in GROUPS + (None,):
            wk = by_week(rows, g)
            a = pf = pc = 0.0
            cells = []
            for w in wks:
                if w in wk:
                    a += wk[w][0]
                    pf += wk[w][1]
                    pc += wk[w][1] * curve[w]
                if w in (3, 6, 9, 12, 15, 18) or w == max(wks):
                    cells.append(f"w{w} {a / pf:.2f}->{a / pc:.2f}")
            print(f"  {(g or 'all'):10} " + "  ".join(dict.fromkeys(cells)))

    # Re-check replay.
    for label, rows, wks in (("2025", rows25, range(1, 18)), ("2026", rows26, range(1, 6))):
        flat, cur = recheck_path(rows, None, wks), recheck_path(rows, curve, wks)
        print(f"\n{label}: re-check multiplier after each week, flat | curve")
        for g in GROUPS:
            print(f"  {g:10} " + "  ".join(f"w{w} {m1:.3f}|{m2:.3f}" for (w, _, m1), (_, _, m2) in
                                         zip(flat[g], cur[g])))

    # How well does the group-level promise (prior x multiplier, with the curve where used) predict what the group
    # pays over the rest of 2025? This is the re-check's job. In sample for the curve's shape.
    print("\n2025: group's rest-of-season points, predicted / actual, at each week (1.00 = right)")
    flat, cur = recheck_path(rows25, None, range(1, 18)), recheck_path(rows25, curve, range(1, 18))
    errs = {"flat": [], "curve": []}
    for g in GROUPS:
        wk = by_week(rows25, g)
        fm, cm = {w: m for w, _, m in flat[g]}, {w: m for w, _, m in cur[g]}
        line = []
        for w in range(1, 17):
            rest = [x for x in wk if x > w]
            act = sum(wk[x][0] for x in rest)
            pf = sum(wk[x][1] for x in rest) * fm[w]
            pc = sum(wk[x][1] * curve[x] for x in rest) * cm[w]
            errs["flat"].append(abs(pf / act - 1))
            errs["curve"].append(abs(pc / act - 1))
            if w in (2, 4, 6, 8, 10, 12, 14, 16):
                line.append(f"w{w} {pf / act:.2f}|{pc / act:.2f}")
        print(f"  {g:10} " + "  ".join(line))
    print(f"  mean miss: flat {sum(errs['flat']) / len(errs['flat']):.1%}, "
          f"curve {sum(errs['curve']) / len(errs['curve']):.1%}")

    # Same, athlete by athlete with the full fair value (blend included), at weeks 4, 8 and 12.
    book25 = pricing.starting_book(pricing.load_csv(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "nfl_2024.csv")), ECON, "NFL")
    rate25 = book25["rate"]
    print("\n2025 athlete by athlete: rest-of-season points predicted by fair value / actual (sum over all 120), and "
          "mean absolute miss per athlete in points")
    for through in (2, 4, 6, 8, 12):
        res = {}
        for label, c in (("flat", None), ("curve A (re-check only)", "A"), ("curve B (re-check + prices)", "B")):
            path = recheck_path(rows25, curve if c else None, range(1, through + 1))
            mults = {g: path[g][-1][2] for g in GROUPS}
            fv = fair_values(rows25, ath25, curve if c == "B" else None, mults, through, gpw25, rate25)
            per = ECON["sports"]["NFL"]["weeks"] * ECON["weekly_yield"] / (ECON["sports"]["NFL"]["games"] * rate25)
            pred, act = defaultdict(float), defaultdict(float)
            for r in rows25:
                if r["week"] > through:
                    ptg = fv[r["id"]] * per  # back from price to points per team game
                    if c == "B":
                        # curve B's price already averages the curve ahead; spread it over the weeks again
                        rest = [w for w in gpw25 if w > through]
                        ahead = sum(curve[w] * gpw25[w] for w in rest) / sum(gpw25[w] for w in rest)
                        ptg = ptg / ahead * curve[r["week"]]
                    pred[r["id"]] += ptg
                    act[r["id"]] += r["points"]
            tp, ta = sum(pred.values()), sum(act.values())
            mae = sum(abs(pred[i] - act[i]) for i in act) / len(act)
            res[label] = f"{tp / ta:.2f} / {mae:5.1f}"
        print(f"  after week {through:2d}: " + "   ".join(f"{k} {v}" for k, v in res.items()))

    # 2026 now: average fair value under each rule (through the games processed so far; re-check through week 5).
    import sqlite3
    conn = sqlite3.connect(f"file:{os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'save', 'game.sqlite')}?mode=ro", uri=True)
    rate26 = float(conn.execute("SELECT value FROM meta WHERE key = 'rate'").fetchone()[0])
    gpw26 = defaultdict(int)
    for w, n in conn.execute("SELECT week, COUNT(*) FROM games GROUP BY week"):
        gpw26[w] = 2 * n
    curve26 = make_curve(share, week18, gpw26)
    live = {i: fv for i, fv in conn.execute("SELECT id, fair_value FROM athletes")}
    print(f"\n2026 curve scaled to 2026's schedule: " + "  ".join(f"w{w} {curve26[w]:.2f}" for w in range(1, 19)))
    for label, c in (("flat (today)", None), ("curve A", "A"), ("curve B", "B")):
        path = recheck_path(rows26, curve26 if c else None, range(1, 6))
        mults = {g: path[g][-1][2] for g in GROUPS}
        fv = fair_values(rows26, ath26, curve26 if c == "B" else None, mults, 6, dict(gpw26), rate26)
        avg = sum(fv.values()) / len(fv)
        by_g = {g: sum(fv[a["id"]] for a in ath26 if a["group"] == g) / sum(1 for a in ath26 if a["group"] == g)
                for g in GROUPS}
        extra = ""
        if c is None:
            gap = max(abs(fv[i] - live[i]) for i in live)
            extra = f"  (largest gap from the save's own prices ${gap:.4f})"
        print(f"  {label:13} multipliers " + " ".join(f"{mults[g]:.3f}" for g in GROUPS) +
              f"  average price ${avg:.2f}  (" + ", ".join(f"{g[4:]} ${v:.2f}" for g, v in by_g.items()) + ")" + extra)


if __name__ == "__main__":
    main()
