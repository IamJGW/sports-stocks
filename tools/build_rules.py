"""Write web/rules.html, the "How it works" page, with every number taken from the game's own settings.

Usage (from sports-exchange/):  python3 tools/build_rules.py
tools/export_economy.py runs this too, so after changing a lever in the workbook the rules page follows.
"""
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import market_maker as MM, pricing  # noqa: E402

OUT = os.path.join(ROOT, "web", "rules.html")
LABELS = {"pass_yd": ("Passing yard", "yards"), "pass_td": ("Passing touchdown", None),
          "int": ("Interception thrown", None), "rush_yd": ("Rushing yard", "yards"),
          "rush_td": ("Rushing touchdown", None), "rec": ("Catch", None), "rec_yd": ("Receiving yard", "yards"),
          "rec_td": ("Receiving touchdown", None), "two_pt": ("Two-point conversion", None),
          "ret_td": ("Kick or punt return touchdown", None), "fum_lost": ("Fumble lost", None)}


def money(x, places=2):
    return f"${x:,.{places}f}"


def pts(x):
    return f"{x:g}"


def build(econ):
    nfl = econ["sports"]["NFL"]
    w, games, weeks = nfl["scoring"], nfl["games"], nfl["weeks"]
    yld, cash, target = econ["weekly_yield"], econ["starting_cash"], econ["target_price"]
    mm, live = econ["market_maker"], econ["live"]
    book = pricing.starting_book(pricing.load_csv(os.path.join(ROOT, "data", "nfl_2025.csv")), econ, "NFL")
    rate = book["rate"]
    groups = pricing.sport_groups(econ, "NFL")

    # Worked dividend example: a quarterback's big afternoon.
    game = {"pass_yd": 300, "pass_td": 3, "int": 1, "rush_yd": 20}
    game_pts = pricing.score(game, w)
    per_share = game_pts * rate
    shares = 100

    # Worked price example: the top-ranked quarterback.
    qb = next(a for a in book["athletes"] if a["group"] == "NFL QB")
    g = groups["NFL QB"]
    qb_weekly = qb["prior_ptg"] * games * rate / weeks

    # Soft cap example: all your cash into one athlete at the target price.
    step = mm["dollars_per_step"] / target
    n_all = MM.most_affordable(target, 0, round(cash * 100), step, mm)
    cost_all = MM.buy_cost_cents(target, 0, n_all, step, mm) / 100
    after_all = MM.mid(target, n_all, step, mm)
    back_all = MM.sell_proceeds_cents(target, n_all, n_all, step, mm) / 100
    bid, ask = MM.quote(target, 0, step, mm)

    k, kw = live["blend_games"], live["recheck_weeks"]
    pb = live.get("promise_by_week") or [1.0] * 18

    rows = "\n".join(
        f"<tr><td>{LABELS[key][0]}</td><td class=num>{'+' if v > 0 else ''}{pts(v)}"
        f"{' (' + pts(v * 10) + ' per 10 yards)' if LABELS[key][1] else ''}</td></tr>"
        for key, v in w.items() if v)
    group_rows = "\n".join(
        f"<tr><td>{html.escape(name.replace('NFL ', ''))}</td><td class=num>{v['lean']:.0%}</td>"
        f"<td class=num>{v['repeat']:.0%}</td></tr>" for name, v in groups.items())

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>How Sports Stocks Works</title>
<style>
:root {{
  --bg: #f7f7f4; --card: #ffffff; --ink: #1d232b; --muted: #5d6673; --line: #dde1e6;
  --accent: #1f5fa8; --good: #1b7a46; --bad: #a33a2b; --tint: #eef3fa;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #14171b; --card: #1c2026; --ink: #e8eaed; --muted: #9aa3ae; --line: #2e343c;
    --accent: #79aef0; --good: #5ec98d; --bad: #f08a7a; --tint: #1f2a38;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #14171b; --card: #1c2026; --ink: #e8eaed; --muted: #9aa3ae; --line: #2e343c;
  --accent: #79aef0; --good: #5ec98d; --bad: #f08a7a; --tint: #1f2a38;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
main {{ max-width: 720px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 1.7rem; margin: 0 0 4px; }}
.sub {{ color: var(--muted); margin: 0 0 20px; }}
nav {{ display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 0 0 24px; font-size: .92rem; }}
nav a, a {{ color: var(--accent); }}
section {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 18px 18px 8px;
  margin: 0 0 16px; }}
h2 {{ font-size: 1.2rem; margin: 0 0 8px; }}
h3 {{ font-size: 1rem; margin: 16px 0 4px; }}
p, li {{ margin: 0 0 10px; }}
ul {{ padding-left: 20px; margin: 0 0 10px; }}
.sum {{ background: var(--tint); border-radius: 10px; padding: 12px 14px; margin: 8px 0 14px; }}
.sum .line {{ display: flex; justify-content: space-between; gap: 12px; }}
.sum .total {{ border-top: 1px solid var(--line); margin-top: 6px; padding-top: 6px; font-weight: 600; }}
.formula {{ font-weight: 600; background: var(--tint); border-radius: 8px; padding: 10px 12px; margin: 6px 0 12px; }}
table {{ border-collapse: collapse; width: 100%; margin: 4px 0 14px; font-size: .95rem; }}
td, th {{ text-align: left; padding: 6px 4px; border-bottom: 1px solid var(--line); }}
th {{ color: var(--muted); font-weight: 600; font-size: .85rem; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.note {{ color: var(--muted); font-size: .9rem; }}
</style>
</head>
<body>
<main>
<h1>How Sports Stocks works</h1>
<p class="sub">Every number on this page comes from the game's current settings.</p>
<nav>
  <a href="#idea">The idea</a><a href="#trading">Buying and selling</a><a href="#dividends">Dividends</a>
  <a href="#prices">Why prices move</a><a href="#winning">Net worth</a><a href="#day">A day in the game</a>
</nav>

<section id="idea">
<h2>The idea</h2>
<p>Every listed NFL quarterback, running back, wide receiver and tight end ({nfl['listed']} of them) is a stock with
a short ticker, like <b>{html.escape(qb['name'])}</b>. You start with <b>{money(cash, 0)}</b> of play money. Buy shares of
the athletes you think will play well. When they play, you're paid a <b>dividend</b> for every share you hold, and
their share price moves with how they're playing.</p>
<p>Nobody owns an athlete outright: any number of players can hold the same star. It's play money only, just for
bragging rights.</p>
</section>

<section id="trading">
<h2>Buying and selling</h2>
<p>You trade with the <b>market maker</b>, a computer trader run by the game. It's always there with two prices for
each athlete:</p>
<ul>
  <li><b>Buy price:</b> what you pay for a share.</li>
  <li><b>Sell price:</b> what you get for a share.</li>
</ul>
<p>The two are {mm['spread']:.0%} apart. For an athlete worth {money(target)}, you'd buy at about {money(ask)} and sell
at about {money(bid)}. So buying and selling straight back always loses a little. The game is for picking athletes
who will do well, not for flipping shares.</p>
<h3>The more people own, the higher the price</h3>
<p>Every {money(mm['dollars_per_step'], 0)} worth of an athlete that players hold pushes his price up
{mm['lean_per_step']:.0%}. Selling brings it back down. Each share in a big order is priced one at a time, so a big
order costs more per share than a small one. The game shows you the total, the average price and his price after
your trade before you confirm.</p>
<p>There's no limit on how much of one athlete you can own, but it gets expensive. Put all {money(cash, 0)} into one
{money(target)} athlete and you get <b>{n_all:,} shares</b>, not {int(cash / target):,}, at an average of
{money(cost_all / n_all)}. His price ends up at {money(after_all)}. Sell it all straight back and you'd get
{money(back_all, 0)}.</p>
<h3>No trading during his game</h3>
<p>Once an athlete's game kicks off, the market maker stops trading him until the overnight update. Otherwise you
could watch a three-touchdown first half and buy at yesterday's price.</p>
</section>

<section id="dividends">
<h2>Dividends: how you get paid</h2>
<p>After each game, the athlete's stats are turned into <b>fantasy points</b> (half-point-per-catch scoring):</p>
<table>
<tr><th>Each</th><th class="num">Points</th></tr>
{rows}
</table>
<p>Then the points are turned into money:</p>
<div class="formula">Dividend per share = fantasy points × {money(rate, 4)}</div>
<div class="formula">You're paid = dividend per share × shares you held at the start of game day</div>
<h3>Example</h3>
<p>You own {shares} shares of a quarterback. He throws for {game['pass_yd']} yards, {game['pass_td']} touchdowns and
{game['int']} interception, and runs for {game['rush_yd']} yards.</p>
<div class="sum">
  <div class="line"><span>{game['pass_yd']} passing yards × {pts(w['pass_yd'])}</span><span class="num">{pts(game['pass_yd'] * w['pass_yd'])} pts</span></div>
  <div class="line"><span>{game['pass_td']} passing touchdowns × {pts(w['pass_td'])}</span><span class="num">{pts(game['pass_td'] * w['pass_td'])} pts</span></div>
  <div class="line"><span>{game['int']} interception × {pts(w['int'])}</span><span class="num">{pts(game['int'] * w['int'])} pts</span></div>
  <div class="line"><span>{game['rush_yd']} rushing yards × {pts(w['rush_yd'])}</span><span class="num">{pts(game['rush_yd'] * w['rush_yd'])} pts</span></div>
  <div class="line total"><span>Fantasy points</span><span class="num">{pts(round(game_pts, 2))} pts</span></div>
  <div class="line"><span>× {money(rate, 4)} per point</span><span class="num">{money(per_share, 4)} a share</span></div>
  <div class="line total"><span>× {shares} shares</span><span class="num">{money(per_share * shares)}</span></div>
</div>
<h3>The fine print</h3>
<ul>
  <li><b>Who gets paid:</b> whoever held the shares at <b>midnight Eastern</b> at the start of game day. Buying on
  Sunday morning doesn't get you Sunday's games; buying on Saturday night does. Selling on Sunday morning still gets
  you Sunday's dividend.</li>
  <li><b>Bad games:</b> a game with negative points pays nothing. It never costs you money.</li>
  <li><b>Playoffs:</b> playoff games pay {pts(live['playoff_boost'])}× the normal dividend.</li>
  <li><b>When:</b> dividends land in your cash in the overnight update after the game.</li>
  <li><b>Stat corrections:</b> the NFL sometimes fixes stats days later. The game pays once, on the box score at the
  time, and doesn't take money back or top it up.</li>
</ul>
<p class="note">Why {money(rate, 4)}? It's set so the average listed athlete, at an average price of
{money(target)}, pays about {yld:.0%} of his price in dividends each week of the season ({money(target * yld)} a share a
week). Dividends alone won't make you rich; picking the athletes who beat expectations will.</p>
</section>

<section id="prices">
<h2>Why prices move</h2>
<p>Each athlete has a <b>fair value</b>: what his dividends are expected to be worth. The market maker's prices sit
around it.</p>
<div class="formula">Fair value = expected weekly dividend ÷ {yld:.0%}</div>
<h3>Where the starting price comes from</h3>
<p>Last season's points per game, adjusted for two things that tend to happen the next year: stars cool off a bit
and weaker players catch up a bit (<b>lean toward the group average</b>), and athletes miss games and fall back
(<b>repeat factor</b>). Each position group has its own:</p>
<table>
<tr><th>Group</th><th class="num">Lean to average</th><th class="num">Repeat factor</th></tr>
{group_rows}
</table>
<p>Example, {html.escape(qb['name'])}: {pts(round(qb['ppg'], 2))} points a game last season, leaned to
{pts(round(qb['leaned'], 2))}, times the {g['repeat']:.0%} repeat factor gives {pts(round(qb['prior_ptg'], 2))} expected
points a game. Over {games} games at {money(rate, 4)} a point and {weeks} weeks, that's {money(qb_weekly)} a week, and
{money(qb_weekly)} ÷ {yld:.0%} = <b>{money(qb['price'])}</b>.</p>
<h3>Every night: this season counts more and more</h3>
<p>After each game day, the expected points blend last season's estimate with what he has actually scored this
season. Last season starts out worth {k} games. After {k} games this season counts the same, and by week 12 it
counts three times as much. A game his team played without him counts as zero, so an injury pulls his price down
on its own.</p>
<h3>Every week: re-checking each group</h3>
<p>After the Monday night game, the game checks each position group against what it has actually paid this season.
If wide receivers as a whole are paying 15% more than promised, their prices rise a little. A slow group gets cheaper.</p>
<ul>
  <li>Each week is compared with what that week should pay. Early in the season nearly everyone is healthy, so week 1
  is expected to pay {pb[0]:.2f}× an average week; injuries add up, so from week 7 on it's about {pb[8]:.2f}×, and
  week 18, when teams rest starters, {pb[17]:.2f}×. A hot September alone doesn't make a group dearer.</li>
  <li>Early on, one hot week barely counts: the old estimate is worth {kw} weeks of evidence.</li>
  <li>It moves at most {live['recheck_max_move']:.0%} a week, and stays between {live['recheck_floor']:.0%} and
  {live['recheck_ceiling']:.0%} of the original estimate.</li>
  <li>The market report shows each week's re-check.</li>
</ul>
<h3>And what players do</h3>
<p>On top of fair value, buying pushes an athlete's price up and selling pushes it down (see
<a href="#trading">Buying and selling</a>).</p>
</section>

<section id="winning">
<h2>Net worth: how you're scored</h2>
<div class="formula">Net worth = cash + what selling all your shares would bring right now</div>
<p>Your shares are valued at what the market maker would actually pay for all of them, at the sell price and
including the drop a big sale causes. So buying a pile of one athlete to push his price up never makes you look
richer than you are.</p>
</section>

<section id="day">
<h2>A day in the game</h2>
<ul>
  <li><b>During the day:</b> trade whenever you like, except athletes whose game has started.</li>
  <li><b>Overnight:</b> the game reads the box scores, checks that they add up, pays dividends, updates every fair
  value, and writes the <b>market report</b>: biggest dividends, biggest price moves, and how your portfolio did.
  If a box score looks wrong, nothing is paid until it's fixed.</li>
</ul>
</section>
</main>
</body>
</html>
"""


def main():
    with open(os.path.join(ROOT, "config", "economy.json")) as f:
        econ = json.load(f)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(build(econ))
    print(f"wrote {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
