# Sports Stocks, Milestone 1: the solo NFL prototype

Written 2026-10-18. Status: **steps 1 to 6 built (2026-10-18); the playtest week (step 7) is yours to play.** Justin took
every default in "Decisions for you" and gave a standing OK for ESPN box-score fetches during this milestone.

## Goal

One player (Justin) runs a Sports Stocks market for the 2026 NFL season on his Mac: 120 listed NFL athletes, buying
and selling against the market maker, a portfolio screen, and the nightly job run by hand on real ESPN box scores.
No accounts, no internet hosting.

**Done when:** Justin plays one full real NFL week (Thursday night to Monday night), runs the nightly job each
morning, and every dividend the game paid matches the hand-check workbook to the cent.

## What's in, what's not

| In Milestone 1 | Left for later |
|---|---|
| 120 NFL athletes (QB, RB, WR, TE) listed with tickers | NBA and NHL (Milestone 3) |
| Market orders against the market maker: "buy 50 now", "sell all" | Limit orders and the player order book (Milestone 2) |
| The market maker's full pricing rules, including stepping out during games and the weekly repeat-factor re-check | Other players and seeing their holdings (Milestone 2) |
| Portfolio screen, market screen, athlete page, market report | Leaderboard, sign-in, join codes (Milestone 2) |
| Nightly job run by hand: fetch box scores, check them, pay dividends, update prices, write the report | Running it automatically every night (Milestone 2) |
| Hand-check workbook for each week | Price charts, IPOs for rookies (Milestone 4) |
| Playoff dividend boost as a setting (not exercised; the test week is a regular-season week) | |

## How it's built

Same no-install approach as the other games, with one difference: **the money lives in a small database file on the
Mac, and only Python code touches it.** The web page asks for prices and sends orders; it never changes cash or shares
itself. That is how Milestone 2 works too (there the referee is Supabase), so the rules written now carry over.

- **`serve.py`** runs the game at `http://localhost:8660` (added to the shared `launch.json` as `sports-stocks`).
  It serves the screens and a handful of requests: market list, one athlete, a quote, place a trade, portfolio,
  latest report.
- **`engine/`** (Python, standard library only): the rules.
  - `ledger.py`: the database (SQLite, a single file in `save/`). Every trade and every dividend is a row that is
    never edited or deleted; cash and holdings are added up from those rows. Money is stored in whole cents.
  - `market_maker.py`: quotes, the price of buying or selling a block of shares, and stepping out during games.
  - `pricing.py`: fair value and the weekly repeat-factor re-check.
  - `scoring.py`: half-PPR points from a stat line, using the weights on the workbook's Scoring sheet.
- **`adapters/espn_nfl.py`**: the only file that knows what ESPN's feed looks like. It turns a game into plain stat
  lines (athlete, game, kickoff time, stats). If ESPN changes its feed, this is the one file to fix.
- **`tools/nightly.py`**: the nightly job, run by hand.
- **`tools/export_economy.py`**: reads the levers from `Stat Street Economy.xlsx` into `config/economy.json`, which the
  code reads. Change a lever in Excel, save, run the export, and the game follows.
- **`web/`**: the screens (plain HTML, CSS and JavaScript), sized for a phone first.
- **`tests/`**: Python tests for every money rule, run with one command.

## The economy, carried over from the workbook

These come straight from the workbook and are not re-decided here:

- **Starting cash $100,000** (your call: "whatever you think"; I'm keeping the workbook's number).
- **Listing:** the top 120 NFL QBs, RBs, WRs and TEs by fantasy points per game in **2025**, with at least 6 games.
  This is the "prices set from last season" rule, now one season later. Players who retired or are out for the
  season stay listed; their fair value falls as they miss games (see below).
- **Scoring:** half-PPR, from the Scoring sheet.
- **Dividend rate:** one NFL rate, set so the average listed athlete is expected to pay 2% of a $50 price per week over
  18 weeks. Recomputed from the 2025 season with the same formula as the workbook.
- **Position groups:** NFL QB, RB and WR/TE keep their lean and repeat factors from `calibrate.py`.

The build starts by checking that the Python pricing gives exactly the workbook's numbers on the workbook's own
seasons (prices from 2024, tested on 2025), so the code and the workbook can't drift apart.

## The market maker's rules

### 1. Fair value, updated every night

Fair value is what an athlete is expected to pay, turned into a price: **expected weekly dividend ÷ weekly yield (2%)**.

The expected points per team game blend two things:

- **The prior:** his 2025 points per game, leaned toward his group's average, times the group's repeat factor
  (which already allows for games missed), times the group's **re-check multiplier** (rule 2).
- **This season so far:** his actual 2026 points per team game. A game his team played without him counts as zero,
  so injuries pull his price down by themselves.

Blend: `expected = (K × prior + total 2026 points) ÷ (K + team games played)`, with **K = 4 games** (a new workbook
lever). After 4 games this season counts as much as the prior; by week 12 it counts about three times as much.

Because the season is already in week 7, the game starts from today's fair values: the nightly job first catches up
on weeks 1 to 7, so a hot start or an injury is already in the price when you make your first trade.

### 2. Weekly repeat-factor re-check (new)

The repeat factors were set from older seasons, and one season can run about 10% hot or cold. So once a week, after
the Monday night game, the job checks each group against what it has actually paid this season:

- **Paid vs promised:** for each group, total actual points of its listed athletes so far ÷ total points the prior
  expected over the same team games. Above 1 means the group is running hot.
- **Weighted for luck:** `multiplier = (weeks played × paid-vs-promised + 8) ÷ (weeks played + 8)`. Early in the
  season one hot week barely moves it; by week 12 the season's evidence outweighs the prior about 3 to 2. The 8 is a
  workbook lever.
- **Speed limits:** the multiplier can move at most **5% a week** and stays between **0.8 and 1.2**. Both are levers.
- It changes only the **prior** half of each athlete's fair value. His own season numbers already move his price;
  this rule is for the part of the price that still rests on last year.
- The market report shows each group's paid-vs-promised and its new multiplier, so you can see why, say, every
  running back got 3% dearer this week.

Result: if wide receivers as a whole are paying 15% above their promise, they get re-priced over a few weeks instead
of staying an easy buy all season.

### 3. Quotes and the soft cap

- **Middle price** = fair value × 1.01 raised to (shares the market holds ÷ shares per step). Holding pushes the price
  up, selling pushes it down, as in the workbook's Market Maker sheet.
- **Spread 4%:** you buy at 2% above the middle, sell at 2% below.
- **Steps in dollars, not shares (change from the workbook):** one step = **$5,000 of fair value**, fixed per athlete
  at the start of the season (100 shares of a $50 athlete, 50 shares of a $100 star). Otherwise a $28 goalie or a
  cheap backup would be twice as easy to push around as a star. The workbook's Market Maker sheet gets this lever.
- **Every share is priced on its own:** the 1st share of a block at the current price, the 100th a step higher. You
  see the total and average before you confirm. Buying and immediately selling back always loses the spread, never
  makes money (a test proves it).
- **Soft cap, as you asked:** no hard limit, but the more of one athlete you hold, the dearer the next share. Putting
  your whole $100,000 into one $50 athlete gets you 1,791 shares (not 2,000), at an average of $55.83, and leaves his
  price at $59.75. Selling all of it straight back returns $96,060. So going all in is allowed, but it costs you about
  10% of your shares. The 1% lean is the lever that makes this gentler or harsher.

### 4. Stepping out during games

From his team's kickoff until the next nightly run, the market maker doesn't quote an athlete: his page says
"In a game: trading reopens after the overnight update". Otherwise you could watch a 3-touchdown first half and buy
at yesterday's price. (With no other players in Milestone 1, nobody else can trade him then either; that comes with
the order book.) Kickoff times come from ESPN's schedule.

### 5. Record time

A day's dividends go to whoever held the shares at **midnight Eastern** when that day began. Since every trade is
stored with its time, holdings at any midnight can be added up exactly; nothing has to be snapshotted.

## Dividends

- **Per share** = the game's fantasy points × NFL dividend rate × playoff boost. A negative game pays zero.
- **Playoff boost (your answer):** a new lever, default **1.5×**, for playoff games. Only 14 teams make the NFL playoffs,
  so most athletes pay nothing then; the boost rewards holding the athletes who are still playing. Not used in the
  test week.
- **Paid to the cent:** each holder's total is shares × per-share amount, rounded once to the nearest cent.
- **Paid once:** each athlete's game can pay only once. Running the nightly job twice, or for a day it already ran,
  changes nothing.
- **Stat corrections:** the NFL sometimes corrects stats days later. Milestone 1 pays on the box score at the time of
  the run and doesn't claw back or top up; if a later fetch differs, the report notes it. (Worth revisiting before
  the friends beta.)

## The nightly job (run by hand)

`python3 tools/nightly.py` each morning. It works out which days since the last run haven't been processed and, for
each one:

1. **Fetch** the day's NFL games from ESPN (schedule, then each finished game's box score). Raw files are saved in
   `data/boxscores/2026/` so a run can be repeated without downloading again.
2. **Check before paying.** Every game must be final; every listed athlete whose team played must appear in the box
   score or be marked as not playing; points must be in a believable range; the athletes' totals must match the team
   totals. If anything fails, it stops, pays nothing, and says what was wrong.
3. **Pay** dividends to holders at record time.
4. **Update fair values** and re-centre the market maker on them.
5. **Re-check the groups** if an NFL week has just finished (rule 2).
6. **Write the market report:** biggest dividends, biggest price moves, your portfolio's day, group re-check results.
7. **Write the hand-check workbook** for the week so far.

Steps 3 to 5 happen in one database transaction: either all of a day goes in, or none of it.

`--as-of 2026-10-12` runs it as if it were that morning, which is how the catch-up on weeks 1 to 7 works and how the
tests replay real weeks.

## Screens

- **Market:** all 120 athletes, with ticker, team, position, buy price, sell price, change since yesterday, last game's
  points, and next kickoff. Sort and filter by position. Athletes in a game show "in game".
- **Athlete:** fair value and quotes, this season's game log (points and dividend per share each game), and the buy and
  sell box with a live preview: shares, total, average price, his price after your trade.
- **Portfolio:** cash, net worth, and each holding (shares, average cost, what selling all of it would bring, dividends
  earned so far). Net worth values each holding at what selling all of it would bring, as decided. Below that, your
  activity: trades and dividends, newest first.
- **Report:** the latest market report.

Screens are built for a phone first; with `serve.py --phone` you can open it on your phone over home Wi-Fi.

## The hand check

`checks/nfl-2026-week-NN.xlsx`, written by the nightly job:

- **Box scores:** each listed athlete's raw stats for each game that week, as ESPN reported them.
- **Scoring:** the points weights and the dividend rate, as blue input cells.
- **Your holdings at each record time.**
- **Check:** formulas that score each stat line, work out the dividend per share and your payout, and compare it with
  what the game paid, marked match or mismatch, with a total at the top.

All the scoring and payout cells are Excel formulas, so the workbook checks the game rather than copying its answers.
You can also open the raw ESPN numbers against, say, ESPN's own game page for a spot check of the source.

## Order of work

| Step | What | Suggested model |
|---|---|---|
| 1 | Workbook: new levers (blend weight K, re-check weight, speed limits, step in dollars, playoff boost) and `export_economy.py`; Python pricing matches the workbook to the cent | Opus medium |
| 2 | Ledger and market maker, with tests: round trips always lose, cents add up, cash can't go below zero, record time | Opus medium |
| 3 | ESPN NFL adapter, saved sample games as test files, the checks before paying | Opus medium |
| 4 | Nightly job: paying once, fair value updates, weekly re-check, report; catch up on weeks 1 to 7 | Opus medium |
| 5 | Screens: market, athlete, portfolio, report | Sonnet medium |
| 6 | Hand-check workbook | Sonnet medium |
| 7 | Playtest week, with a tester survey and the dashboard updated | Sonnet medium |

Steps 1 to 4 move play money, so they stay on Opus. Steps 5 to 7 follow settled patterns and can move to a fresh
Sonnet conversation with a handoff brief.

The test week will be the first full NFL week after step 6 is done, most likely week 9 or 10 (early November).

## Downloads I'll need your OK for

From ESPN's public feed, the same source as Milestone 0:

1. **The 2026 schedule**, one small request per week (about 18).
2. **Box scores for 2026 weeks 1 to 7**, one request per game (about 105 games), to catch up on the season and to test
   the adapter on real games. Each is a few hundred KB; I'll keep the raw files for the test weeks and only the
   extracted stats for the rest, so it stays under about 10 MB on disk.
3. **Then the nightly fetch:** about 1 to 16 games a day while you play. When you run the job yourself, that's your
   download. When I run it while building and testing, I'll ask you first, unless you'd rather give a standing OK for
   ESPN box-score fetches during Milestone 1.

## Decisions for you before I start

1. **The re-check's settings:** weight 8 weeks, at most 5% a week, kept between 0.8 and 1.2. They're levers, so this
   is only about the defaults.
2. **Steps in dollars** ($5,000 of fair value) instead of the workbook's 100 shares, so cheap and expensive athletes are
   equally hard to push around.
3. **Playoff boost 1.5×.**
4. **Stat corrections:** pay once at the time of the run and don't revise (for Milestone 1).
5. **Downloads:** OK the ~120 requests in 1 and 2 above, and say whether the nightly fetches during building get a
   standing OK or one each time.

Still open but not needed for Milestone 1: **should fair value fall as the season runs out?** Your answer covered
playoff dividends but not this half. Under the current rule an athlete's price doesn't know that only 2 weeks are
left, so late in the season everyone is overpriced compared with what they can still pay. It matters for the friends
beta (December to March crosses the end of the NFL season), so I'll bring it back before Milestone 3.

## Progress (2026-10-18)

Steps 1 to 4 are built and tested (`python3 tests/run.py`, 27 tests). See `README.md` for the commands.

- **Step 1:** the workbook has a Live Rules sheet (blend weight, re-check settings, playoff boost) and the Market
  Maker sheet's step is now in dollars. `tools/export_economy.py` writes `config/economy.json`. The Python starting
  prices equal the recalculated workbook's to within a millionth of a cent.
- **Step 2:** `engine/ledger.py` and `engine/market_maker.py`. Trades and dividends can't be edited or deleted (the
  database refuses). Tested: round trips always lose, cents round against the player, no overspending or
  overselling, a moved price is refused, the step-out window, net worth at liquidation value.
- **Step 3:** `adapters/espn_nfl.py`. Before paying it checks that each game is final, the athletes' rows add up to
  the team totals, every yard thrown was caught, and the numbers are believable. All 91 finished 2026 games passed.
- **Step 4:** `tools/nightly.py`. The real save (`save/game.sqlite`) is caught up through week 5 and Thursday of week 6
  (80 games). Sunday's week 6 games pay on the next morning's run.
- **Correction to the plan:** the season was in week 6, not week 7, on 2026-10-18 (it started Wednesday 9 Sept).
- **Team changes:** an athlete's team comes from the latest box score he appears in; six listed athletes haven't
  played yet in 2026 and keep their 2025 team (Jacobs, Fields, Charbonnet, Flacco, Rattler, Mills).

**A surprise to look at before the friends beta:** through week 5, every NFL group has paid well above its promise
(QBs 116%, RBs 106%, WRs/TEs 127%), so the re-check has raised their multipliers to 1.06, 1.02 and 1.10 and the
average price is up from $50 to about $56. The likely reason is that the repeat factors allow for a whole season of
missed games, and injuries pile up late in the season, so the early weeks run hot and the late ones should run cold.
If that's right, the re-check is chasing a pattern that reverses. Checking it needs 2025's week-by-week box scores
(about 270 games) to see whether 2025 ran hot early too; if so, the fix is to promise by week (an availability
curve) instead of a flat share of every game.

## Progress, steps 5 and 6 (2026-10-18)

Built and tested (`python3 tests/run.py`, 36 tests).

- **Step 5, screens:** `serve.py` (port 8660, `--phone` for a phone on the Wi-Fi, `--save PATH` to try things on a
  copy) serves `web/` and a small JSON API (`engine/api.py`). Market (search, position filter, sort, "in game"),
  Athlete (buy/sell box with live preview, "All in" and "Sell all", game log, price history), Portfolio, Report. A
  refused trade's message goes to the page as written by the ledger. The page never works out money. Checked in the
  Browser pane at phone size against a copy of the save (a 100-share buy, preview equal to the fill). Added to
  `launch.json` as `sports-stocks`; it uses the real save, so use `--save` on a copy for experiments.
- **Step 6, hand check:** `tools/hand_check.py` writes `checks/nfl-2026-week-NN.xlsx` (Check, Scoring, Trades
  sheets); `tools/nightly.py` writes the workbook for each week it touched. Scoring weights, rate and playoff boost
  are blue inputs; points, per-share dividend, holdings at record time (from the Trades sheet) and payout are
  formulas, compared with what the game paid ("match" or "MISMATCH", counts at the top). Recalculated with
  LibreOffice. Replayed week 5 on a scratch save with buys, a sell and trades either side of record time: 88 lines,
  0 mismatches, $1,119.85 paid and recalculated. Weeks 1 to 6 of the real save also give 0 mismatches (no trades yet).
  A test edits a weight in the workbook and sees mismatches appear, so the formulas are live.
- **Step 7:** survey written (`playtest/surveys/sports-stocks-m1-week.json`). Week 7 starts Thu 22 Oct.
