# Acceptance: Milestone 2, ready for the two-house test

Written 2026-11-01, before any of the code it describes.

**What this milestone is.** The handoff (`~/.claude/handoffs/sports-stocks-2026-10-29-m2-step6-pages.md`) has one step left,
the switch to the live project. That step is held until about Tue 3 Nov and needs Justin's OK part by part, so it is
**not** in here. This milestone is everything else Milestone 2 still owes, on the **test** project and the public
GitHub Pages site, so that the switch and the two-house test (plan step 7) find nothing broken.

**Not in here, on purpose:** live migrations, season upload to live, the live secret, live SMTP and template, `config.js`
to live, nightly `--target live`, switching off the Mac's 4:00 job, creating live users. Nothing in this milestone
touches the live project.

Status key: `[ ]` not yet, `[x]` passed. Every box is a command or a browser flow that says pass or fail on its own.

**Result, 2026-11-01: every box below passes.** 108 tests; 34 of 34 flows locally; 32 of 32 on the public site, deployed
from commit 11a9141 (16 at each size: B02 ran at desktop only and B03 at iPhone only, with a person typing real codes).
Screenshots and results are in `checks/browser/`.

## 1. What Supabase actually sends (inspected 2026-11-01, not assumed)

Read from the test project's auth settings and from admin `generate_link`, which makes a code without sending mail:

| Question | Found |
|---|---|
| Code format | six digits, `999999` (`mailer_otp_length` 6), good for an hour (`mailer_otp_exp` 3600) |
| Returning player's email | "magic link" template: subject "Your sign-in link", body shows `{{ .Token }}` |
| **New player's email** | **"confirmation" template, still Supabase's default: no code, only a link** |
| Where that link goes | `site_url`, still **`http://localhost:3000`** |
| Proof of the path | Justin's own account has `confirmation_sent_at` at first sign-in, later sign-ins `recovery_sent_at` |

So today **a friend's first sign-in cannot work**: the page asks for a code, the email has none, and its link goes to
a page that doesn't exist. Fixing that is criterion AUTH-1 to AUTH-4.

## 2. Unit and database tests (`python3 tests/run.py`)

### Sign-in settings (`tests/test_online_auth.py`, `tools/auth_setup.py`)
- [x] **AUTH-1** Both email templates on the test project show `{{ .Token }}`, and neither contains `ConfirmationURL`
  or any other link.
- [x] **AUTH-2** `mailer_otp_length` is 6 and both templates say 6 digits; both subjects name the game.
- [x] **AUTH-3** `site_url` on the test project is the public site, not localhost.
- [x] **AUTH-4** A brand-new address's code (`generate_link` type `signup`) and a returning player's code (type
  `magiclink`) are both six digits, and both sign in through `verify` with type `email`, the call the page makes.
- [x] **AUTH-5** `tools/auth_setup.py test` changes only those fields: the SMTP host, port and sender and the rate limits
  read the same before and after. `tools/auth_setup.py` won't touch live without `--yes-live`.

### Market list (`db/migrations/006_market_list.sql`, `tests/test_online_market_list.py`)
- [x] **DB-1** Migration 006 applies to the test project with `tools/db.py test push`, each file recorded as done.
- [x] **DB-2** `tools/db.py test status` passes its safety check: row-level security everywhere, phones can't write, phones
  call only `db/phone_functions.txt`.
- [x] **DB-3** `market_list` is in `db/phone_functions.txt`, pinned (`security definer`, empty `search_path`), and refuses a
  phone that isn't in the league and a phone that isn't signed in.
- [x] **DB-4** For every athlete it returns the last trade, best bid and best offer. Each agrees with `order_book` for
  the same athlete, cases: no trades; player bid better than the market maker; player offer better; market maker
  holding none (no bid); market maker out (his prices left out); a sleeping order (not counted as best).
- [x] **DB-5** It is read-only: nothing changes and `check_league` stays clean.
- [x] **DB-6** It answers for all 120 NFL athletes in under 2 seconds.

### Hand check from the database (`tools/hand_check.py --online`, `tests/test_online_robot.py`)
- [x] **HC-1** After a pretend day with two players, the workbook for each player recalculates in LibreOffice with zero
  mismatches, and its total equals that member's rows in `dividends` to the cent.
- [x] **HC-2** A player-to-player trade counts for the buyer's and the seller's holdings at record time.
- [x] **HC-3** Changing one paid amount in the data makes the workbook say MISMATCH (the check can actually fail).

### The site's files (`tests/test_web_static.py`)
- [x] **WEB-1** `web/manifest.webmanifest` is valid: name, short name, `display: standalone`, relative `start_url` and `scope`,
  icons at 192 and 512.
- [x] **WEB-2** The icons and a 180 px apple-touch-icon are real PNGs of the size they claim, and `index.html` links them.
- [x] **WEB-3** Every local file `index.html` and the manifest name exists, and every path is relative, so the site
  works under `/sports-stocks/`.
- [x] **WEB-4** No secret key, access token or `service_role` text anywhere in `web/`, and `config.js` points at the test
  project (the switch is a separate step).
- [x] **WEB-5** The page's sign-in box takes the length Supabase is set to, and `app.js` calls `verifyOtp` with type `email`.

## 3. Browser flows (`python3 tests/browser/flows.py`)

Real Chrome, driven with the standard library only (`tests/browser/chrome.py`); nothing to install. Real clicks and taps,
which fail if something covers the button. Viewports: **desktop** 1280×800, and **iPhone** 390×844 at 3× with touch and
the iPhone browser identity. Each flow fails on a page error, a failed request it didn't expect, or a wrong number.
Screenshots go to `checks/browser/<target>-<viewport>-<flow>.png`.

| Flow | Must show |
|---|---|
| **B01 shell** | Loads with no errors; every file 200; manifest and icons load; on live: HTTPS, and each file byte-identical to `web/` |
| **B02 sign-in, returning** | Email, then code screen; a wrong code gives a plain message and lets you retry; the right six digits sign in; a pasted `123 456` with a space works |
| **B03 sign-in, new player** | A never-used address signs in with a code alone and lands on Leagues or Market |
| **B04 league** | Create a league in the form; join another by opening a `?join=CODE` link |
| **B05 market list** | Each row shows last trade, best bid and best offer as the database says; search and position chips work |
| **B06 market buy** | Preview equals the fill equals the trade row in the database, to the cent |
| **B07 limit and cancel** | A limit sale waits, shows in the book and in my open orders; Cancel removes it |
| **B08 two players** | The other player's order appears within 10 seconds with no reload; I fill it at their price; both see the trade by name |
| **B09 portfolio** | Net worth, cash, set aside, free, holdings and open orders equal the database; cash equals the start minus my trades |
| **B10 league** | Leaderboard shows both players in order; tapping one shows their holdings |
| **B11 report** | A report with an overnight fill shows that fill |
| **B12 banner** | A late day shows the delayed banner with the robot's reason; no late day shows none |
| **B13 how it works** | Rules load under the site's sub-path, and a `?` link lands on its section |
| **B14 partial fill** | A market buy bigger than my cash fills what it can and says how many weren't ordered |
| **B15 stays signed in** | A reload keeps me signed in; Sign out returns to the sign-in screen |
| **B16 phone layout** | On every screen: no sideways scroll, inputs at 16 px or more (iPhone Safari zooms below that), header doesn't cover content, tap targets at least 32 px |
| **B17 evening date** | At 9:30 p.m. Eastern the new-league date defaults to today in Eastern time, the day the database uses |

- [x] **BR-LOCAL** All 17 flows pass on `localhost` at desktop and iPhone.
- [x] **BR-LIVE** All 17 flows pass on https://iamjgw.github.io/sports-stocks/ at desktop and iPhone.

**Sign-in on each target.** Locally the script uses fake `@example.com` testers: the request that would mail them is
stubbed so nothing bounces, and it types a code from `generate_link`. On the public site **Justin types his email and
code** (B02 at one viewport, B03 with a never-used address at the other), because Claude doesn't enter sign-in codes on
a public host. That is also the only proof a real email arrives with a real code, so it isn't a shortcut. All the
other flows on live are scripted.

**The second player** is a fake tester calling the same database functions the page calls.

## 4. Deploy

- [x] **LIVE-1** The Pages workflow succeeds and the site serves the new files (B01 compares bytes).
- [x] **LIVE-2** A failure on live that passed locally is fixed in the hosted build and rerun, not explained away.
- [x] **LIVE-3** The nightly robot still succeeds on the test project after migration 006.

## 5. Step 7's kit and the record

- [x] **DOC-1** `TWO_HOUSE_CHECKLIST.md` for the two-house test (plan, "Testing two houses").
- [x] **DOC-2** A tester survey and watching sheet for that round, per `Games_Dev/CLAUDE.md`, and the old round handled.
- [x] **DOC-3** `MILESTONE_2_PLAN.md`, `README.md`, the project memory and `dashboard/projects.json` updated; dashboard rebuilt.
- [x] **DOC-4** Justin asked before anything is committed.

## 6. What needs a person (cannot be scripted)

- **Real iPhone Safari.** The iPhone flows ran in Chrome at iPhone size, screen and touch. This Mac has no Xcode, so
  no Simulator, and Chrome isn't Safari. The first real test is step 7.
- **The two-house test** (plan step 7, `TWO_HOUSE_CHECKLIST.md`): two people, two houses, real networks, real mobile data.
- **A sleeping order across a real game**, and a real morning report with real overnight fills. The flows check the
  screen with a made-up report, and the database tests check the fills.
- **Add to home screen on a real phone.** The files are checked; the install itself is a phone's own menu.
- **Whether friends understand Bid, Offer and Last.** The survey asks.
- **The live switch**, each part with Justin's OK: SMTP on the live project is typed into Supabase by hand.

## 7. What the run taught the tests

- At the first run, 2 of 34 flows passed; 25 of 34 once a scratch copy got past sign-in. The flows that already passed
  covered existing features, so each was then run against a site broken on purpose (a wrong preview, Cancel dead, wrong
  free cash, leaderboard reversed, no overnight fills, no banner, rules missing, partial fill unsaid, sign-out kept).
  All nine breaks were caught.
- B17 first passed for a bad reason: a hash-only jump never reloaded the page, so its fake clock didn't run. The flow
  now checks the clock is running.
- Two test runs on this Mac at once (another conversation's `tests/run.py`) closed each other's leagues and looked just
  like a matching bug: a crossed book and "This league is over". `tests/online.py` now takes turns with a lock.
- The privacy test `test_signed_in_phone_sees_no_league_it_isnt_in` failed now and then because tester01 is in over 1,000
  leagues and a request stops at 1,000 rows, so it compared two different thousands. Checked from both ends of the limit
  on six tables for three testers: no row from a league they aren't in. The test now takes the whole list with the
  secret key. No leak.
- A Supabase 502 failed seven tests once. Management calls now try again on 502 to 504.
