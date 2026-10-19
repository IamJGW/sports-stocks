# Sports Stocks (folder: sports-exchange)

Fantasy sports dressed as a stock exchange. Design and roadmap: `PROJECT_PLAN.md`. Current milestone:
`MILESTONE_1_PLAN.md` (solo NFL prototype on this Mac). Standard-library Python 3.9 only; nothing to install.

## Commands (run from this folder)

| What | Command |
|---|---|
| Start a new market (once) | `python3 tools/new_game.py` |
| The nightly job, each morning | `python3 tools/nightly.py` |
| Same, one line per day | `python3 tools/nightly.py --quiet` |
| Replay as if it were a past morning | `python3 tools/nightly.py --as-of 2026-10-12` |
| Use only saved box scores | `python3 tools/nightly.py --offline` |
| Copy the workbook's levers into the game (also rebuilds the rules page) | `python3 tools/export_economy.py` |
| Rebuild the "How it works" page, `web/rules.html` (also the app's How it works tab) | `python3 tools/build_rules.py` |
| Rebuild the economy workbook | `python3 tools/build_economy_workbook.py` |
| Play (screens at http://localhost:8660) | `python3 serve.py` |
| Same, also open on a phone over Wi-Fi | `python3 serve.py --phone` |
| Try things on a copy of the save | `python3 serve.py --save path/to/copy.sqlite` |
| Hand-check workbook for a week | `python3 tools/hand_check.py --week 6` |
| Run the tests | `python3 tests/run.py` |

## The automatic morning run

The Mac runs the nightly job by itself at **4:00 a.m.** and again at **9:00 a.m.** (a retry; it does nothing if 4:00
worked). If the Mac is asleep then, it runs when it wakes; if it's shut down, the next scheduled time catches up on
every missed day. Each run adds to `save/morning.log` and shows a notification: "overnight update done" or "stopped"
(a game not final yet, or a box score that doesn't add up: nothing is paid for that day until a later run succeeds).

| What | Command |
|---|---|
| Run it now, the same way | `bash tools/morning.sh` |
| Is it installed, and how did the last run end? | `launchctl print gui/$(id -u)/com.sportsstocks.morning` (look at "runs" and "last exit code") |
| Turn it off | `launchctl bootout gui/$(id -u)/com.sportsstocks.morning` |
| Turn it back on | `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sportsstocks.morning.plist` |

The schedule is `tools/com.sportsstocks.morning.plist`; the installed copy is in `~/Library/LaunchAgents/`. After
editing the one in `tools/`, copy it over, then turn it off and on again.

The save is `save/game.sqlite`; each night's market report is also written to `save/reports/<date>.txt`.
To start over, move `save/` aside and run `new_game.py` again.

## Where things are

- `engine/`: the rules. `ledger.py` (the books: trades, cash, holdings, portfolio), `market_maker.py` (prices),
  `pricing.py` (fair value, weekly group re-check; same formulas as the workbook), `nightly.py` (the overnight update).
- `engine/api.py`, `serve.py`, `web/`: the screens (Market, Athlete, Portfolio, Report). The page only asks and orders.
- `tools/hand_check.py`: `checks/nfl-<season>-week-NN.xlsx`, recalculating each dividend from ESPN's raw stats.
  The nightly job writes it for the weeks it processes.
- `adapters/espn_nfl.py`: the only code that knows ESPN's feed. Downloads are kept in `data/espn_nfl_2026/`.
- `config/economy.json`: the levers, exported from the workbook. Don't edit by hand; edit the workbook and export.
- `tests/`: every money rule has a test. `tests/fixtures/` holds one real box score.
