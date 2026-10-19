# Availability curve: do NFL groups pay above their promise early and below it late?

Written 2026-10-19. **Option A adopted the same day** (Justin's OK): the weekly re-check uses the curve; prices
(option B) don't yet. See "Adopted" at the end.

Scripts (run from `sports-exchange/`):

- `python3 research/fetch_nfl_2025.py` downloads 2025's regular season (18 schedules, 272 box scores, 13 MB) into
  `data/espn_nfl_2025/` (left out of git). All 272 passed the adapter's checks before paying.
- `python3 research/availability.py` shows paid vs promised and the share of games played, week by week.
- `python3 research/curve.py` fits the curve on 2025 and tests it on 2026.

2025 is priced from 2024 exactly the way the game prices 2026 from 2025: the same listing rule, the same lean and
repeat factors, the same levers. 2026 comes from the real save, opened read-only. As a check, the script rebuilt
today's 2026 prices from scratch and matched the save to the cent.

## 1. Did 2025 run hot early and cold late? Yes, though less than 2026

Paid ÷ promised for all 120 listed athletes. "Played" is the share of their teams' games in which they appeared:

| Week | 1 | 2 | 3 | 4 | 5 | 6 | 7–10 | 11–14 | 15–16 | 17 | 18 | Season |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025 paid ÷ promised | 1.07 | 1.18 | 0.96 | 1.02 | 1.11 | 0.95 | 1.00 | 0.90 | 1.04 | 0.82 | 0.61 | 0.96 |
| 2025 played | 86% | 86% | 82% | 80% | 72% | 73% | 73% | 75% | 75% | 70% | 59% | 75% |
| 2026 paid ÷ promised | 1.26 | 1.14 | 1.21 | 1.11 | 1.11 | 0.96* | | | | | | 1.14 |
| 2026 played | 88% | 83% | 84% | 78% | 77% | 78%* | | | | | | 82% |

\* Week 6 of 2026 is still missing Monday night's game.

Most of the pattern comes from games missed, not from points per game. When a listed athlete does play, he scores
about the same all season (1.2 to 1.4 times his per-team-game promise, with no trend until week 18). But the share of
his team's games he plays in falls from about 87% in week 1 to about 73% by week 5, then holds flat until the last
week. The repeat factors were set on whole seasons, so they promise that 73–75% all year. Week 1 is bound to look hot
and week 18 cold. Week 18 is the worst week by far, because teams rest their starters, so even players who appear
score less.

In 2025 the flat rule led the re-check the wrong way. It raised QBs to 1.05 by week 5 and held them there until week
10. Over the rest of the season QBs paid well under that.

## 2. The proposed curve: promise by week

The curve was fitted on 2025's played share for weeks 1 to 17. A smooth decline fits it: 87.9% at the start,
settling at 73.5%, with most of the drop over the first three weeks (time constant 2.4 weeks). Week 18 is set from
what 2025's week 18 paid, because there even the players who appeared scored little. The curve is scaled so that it
averages exactly 1 over the season's team games. **The repeat factors still set each season's total; the curve only
moves that promise between weeks.**

| Week | 1 | 2 | 3 | 4 | 5 | 6 | 7–8 | 9–17 | 18 |
|---|---|---|---|---|---|---|---|---|---|
| Promise × | 1.18 | 1.12 | 1.07 | 1.04 | 1.02 | 1.01 | 1.00 | 0.99 | 0.64 |

It would be one new row of 18 levers on the workbook's Live Rules sheet, exported like the others.

## 3. Honest checks

**Out of sample (2026, never used in the fit): does the curve predict who plays?** Yes, closely.

| Week | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| 2026 played share | 87.5% | 83.3% | 84.2% | 78.3% | 77.2% | 77.6% |
| 2025 curve predicted | 87.9% | 83.0% | 79.8% | 77.6% | 76.2% | 75.3% |

**Out of sample: how much of 2026's hot start does it explain?** About 8 of the 14 points.

| Group | Paid ÷ promised through week 6, today's flat promise | With the curve |
|---|---|---|
| QB | 1.15 | 1.07 |
| RB | 1.02 | 0.95 |
| WR/TE | 1.23 | 1.14 |
| All | 1.14 | 1.06 |

What's left looks real, mainly wide receivers and tight ends scoring more per game than last year. Chasing that is
the re-check's job, and with the curve it would still chase it.

**In sample (2025, the season the curve was fitted on), so these figures are optimistic:**

- The re-check's job is to predict what a group will pay over the rest of the season. Averaged over weeks 1 to 16 and
  the three groups, that prediction missed by **13.5% under the flat rule and 4.6% with the curve**.
- Athlete by athlete, fair value predicted the rest of 2025's dividends **11–13% too high all season under today's
  rules**. With the curve applied to prices too (option B below) the miss was 0–3%. The curve hardly changes how
  well athletes are ranked against each other (the typical miss per athlete is about the same). It fixes the overall
  price level, not the order.

**What isn't tested:** the part of the curve after week 6 has been seen in one season only, so it has no
out-of-sample check yet. The most fragile number is week 18's 0.64. It comes from one week of one season and depends
on how many teams have already clinched their playoff place. Also, one curve is used for all three groups. In 2025
QBs lost less availability early than RBs and WR/TEs did (71%→67% against 94%→78% and 91%→81%). With a single
season, separate group curves would mostly be fitting noise.

## 4. What it would have done to 2026 weeks 1 to 6

Re-check multipliers after week 5, and fair values now, with the re-check run through week 5 and prices including
Sunday of week 6:

| | QB mult | RB mult | WR/TE mult | Average price | QB | RB | WR/TE |
|---|---|---|---|---|---|---|---|
| Today (flat) | 1.062 | 1.023 | 1.102 | $55.55 | $61.11 | $57.51 | $49.83 |
| A: curve in the re-check only | 1.026 | 0.991 | 1.063 | $54.80 | $60.30 | $56.76 | $49.14 |
| B: curve in the re-check and in prices | 1.026 | 0.991 | 1.063 | $50.34 | $55.39 | $52.15 | $45.14 |

- **Option A** changes one line: the re-check's promise becomes the prior times the curve value for each team game.
  Multipliers fall by about 3.5%, but prices only by about 1.3%, because the multiplier only touches the prior half
  of the blend.
- **Option B** also changes fair value in two places. The season so far is measured against the curve, so a fast
  start in the healthy early weeks counts for less. The price also looks ahead at the average curve value of the
  weeks still to come, which falls once week 18 is in view. Prices drop about 9%, back near the $50 target. In 2025
  that was the version whose price level came out right.

## Recommendation

1. **Adopt option A now.** The part it relies on (weeks 1 to 6) held up out of sample, and it stops the re-check
   chasing a pattern that reverses.
2. **Before option B, download 2024's week-by-week box scores** (about 272 games, the same size as 2025's). The
   curve could then be fitted on 2024 and tested on all of 2025, including the late weeks and week 18, which are the
   numbers option B leans on. That needs your OK for the download.
3. Either way it's one row of levers in the workbook, plus tests showing a flat row (all 1s) reproduces today's
   prices exactly.

## Adopted: option A (2026-10-19)

- The 18 values are a table on the workbook's Live Rules sheet ("NFL promise by week (re-check)"), exported as
  `live.promise_by_week`. All 1s gives the old rule exactly (a test checks this).
- `engine/nightly.run_recheck` weighs each team game by its week's promise; weeks outside 1-18 count as 1.
- A save keeps the levers it started with, so `tools/apply_live_rules.py` copies the Live Rules levers into a save
  (keeping a copy of it first). Run on the real save; the copy from before is
  `save/game.sqlite.before-live-rules-20261019-160941`.
- Weeks 1-5's re-checks stay in the history as they ran. The re-check after week 6 compares the whole season so far
  against the curve, so it catches up in one step (within the 5% limit). Preview on a copy with 13 of week 6's 14
  games: QB 1.062 -> 1.029, RB 1.023 -> 0.978, WR/TE 1.102 -> 1.061; average price $55.45 -> $54.74.
