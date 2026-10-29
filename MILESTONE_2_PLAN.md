# Sports Stocks, Milestone 2: the online league

Written 2026-10-28. Status: **decisions answered 2026-10-28 (see "Decisions"); building started the same day.** Step 1 waits on your
GitHub and Supabase accounts for anything that touches the internet.

## Goal

Move the game from Justin's Mac onto the internet so a league of friends can play from their phones: sign in, create
or join a league with a code, trade with each other through an order book as well as with the market maker, and get
dividends and a market report every morning from a robot that runs without the Mac.

**Done when:** two phones in different houses trade with each other and with the market maker, and both see the same
book. In practice that means a scripted 30-minute session (step 7) in which each phone sees the other's order appear
within 10 seconds, one fills the other's order, both see the trade, and the next morning's dividends for both players
match the hand-check workbook to the cent.

**Calendar.** Today is 28 Oct. Five weeks takes us to about 2 Dec, which leaves room for the friends beta (Milestone 3:
NFL, NBA and NHL; 5-8 friends, then up to 20) to start in mid-December. Milestone 2 is NFL only; NBA and NHL are
Milestone 3's main job (see "What can slide to the beta").

## What's in, what's not

| In Milestone 2 | Left for later |
|---|---|
| Sign-in with an emailed 6-digit code; a display name | Passwords, Google sign-in (an option, see decisions) |
| Create a league (name, start and end dates), join with a 6-character code or link, at most 20 players | Public exchange, private invites by email (Milestone 6) |
| One order book per athlete per league: market orders and limit orders, matched inside the database | Short selling, stop orders, price alerts |
| The market maker in every book, with its Milestone 1 rules, stepping out during games | A thinner market maker for big markets (Milestone 6) |
| Cancel an order; your open orders on one screen | Editing an order (cancel and place again instead) |
| Leaderboard; every player's holdings visible to the league | Price charts (Milestone 4) |
| Nightly robot on GitHub Actions: box scores, dividends, fair values, re-check, report, and an alert when it stops | Stat corrections paid later (decide before the beta) |
| Market report per league | Weekly email digest (Milestone 4) |
| Hosting on GitHub Pages, phone-first, can be added to the home screen | App stores |
| Hand-check workbook reading from the online database | |
| NFL only | NBA and NHL adapters and listings (Milestone 3) |

## How it's built

The Milestone 1 rule still holds: **the page only asks and orders; it never works out money.** In Milestone 1 the
referee was Python on the Mac. Now there are two referees, each doing what it is good at:

| Runs where | What | Why there |
|---|---|---|
| **Inside the database** (Supabase, Postgres functions) | Placing, matching and cancelling orders; the market maker's prices; cash and share checks; stepping out during games; the leaderboard | Trades happen live, from many phones at once. Only the database can make sure two people can't take the same shares, and nobody can edit it from a browser. |
| **The nightly robot** (Python, GitHub Actions; same script runs on the Mac) | Fetching box scores and the checks before paying; scoring; dividends; fair values and the weekly re-check; the market report; the hand check | This is the Milestone 1 code that already matches the hand check to the cent. Rewriting it in SQL would mean proving it all over again. |

### What moves, what stays, what's thrown away

- **Stays as is:** `adapters/espn_nfl.py`, the checks before paying, `pricing.py` (fair value, the re-check, the promise
  by week), `nightly.dividend_cents`, the report text, `export_economy.py` and the workbook levers.
- **Rewritten in SQL:** `market_maker.py`'s arithmetic (middle price, block cost, block proceeds) and the trade rules in
  `ledger.py`. The Python versions stay as the **reference**: a test runs both on thousands of random cases and on
  every trade in the real save, and they must agree to the cent.
- **New in SQL:** the order book and matching (below), league setup, the rules about who may read what.
- **Changed:** `tools/nightly.py` gets an online mode that talks to Supabase over HTTPS (standard library only; Python
  can't talk to Postgres directly without an add-on, so it calls database functions through Supabase's web API).
  `tools/hand_check.py` gets a reader for the online database.
- **Thrown away:** `serve.py`'s API and `engine/api.py` (the database functions replace them). The screens in `web/`
  are kept and get a new data layer. The solo save on the Mac stays as a record; its 4:00 a.m. job is switched off once
  the robot has run three clean nights online.

### Two Supabase projects

The free plan allows two. **`sports-stocks`** is the real one. **`sports-stocks-test`** is a bench that the tests can
wipe and rebuild at will; every step is built and tested there first. There is no Postgres on the Mac (nothing to
install), so the tests run against the test project over the internet.

### Database changes

Each change to the database is a numbered SQL file in `db/migrations/`. `tools/db.py` applies the ones a project hasn't
had yet and records them, using Supabase's management web API with a personal access token that you create and keep
in a file on the Mac (see "What you need to do"). Claude never sees the token; the script reads it from the file.

## The data

Every table has row-level security switched on: a phone can read only what it's allowed to, and **no phone can write
to any table directly.** Every change goes through a database function that checks who is asking.

**Shared by every league** (written only by the robot): the season and its levers, athletes (ticker, team, position,
group, prior, steps, fair value), groups and their re-checks, the schedule (kickoff times), stat lines, per-share
payouts, daily fair values, and a robot status row (last day processed, last stop and why).

**Per league** ("market" in the database, so the public exchange later is just one very big market):

- **markets:** name, join code, creator, start and end dates, at most 20 players, starting cash, and the market
  maker's levers copied in at creation (a league keeps the levers it started with, as a save does now).
- **members:** who, display name (unique in the league), joined when, starting cash.
- **orders:** who, athlete, buy or sell, market or limit, shares, limit price in whole cents, shares still open,
  status (open, filled, cancelled), placed and closed times, why closed.
- **trades:** time, athlete, buyer, seller (either can be the market maker), shares, total cents, the two orders, and
  for market maker fills the fair value and its holdings before (as in Milestone 1). **Final: a trigger refuses any
  edit or delete**, as the SQLite save does now.
- **dividends:** game, athlete, player, shares at record time, cents. **Final**, same trigger.
- **reports:** one per league per day.

Cash and holdings are still added up from trades and dividends; there is no running balance. Times come from the
database clock only; a phone never sends a time.

## The order book's rules

This is the part the roadmap asks Opus at high effort to review before any money moves through it (step 3).

### Orders

- **Limit order:** "buy 50 JOKIC at $38.00 or less". Prices are whole cents per share. It fills what it can now and the
  rest waits in the book until it fills, you cancel it, or the league ends.
- **Market order:** "buy 50 now". It fills **as many as it can right now**, at the best prices in the book, and tells
  you how many it got: "Bought 30 of 50: only 30 were for sale (the market maker is out while he plays). The other 20
  were not ordered." The rest never waits in the book; for that, use a limit order. **Price guard:** no share fills
  above the dearest share in your preview (sales: below the cheapest), so if the book moves against you between the
  preview and the tap, you get fewer shares, never a worse price. A buy also stops where your cash runs out. In the
  database a market order is simply a limit order at the preview's worst price that cancels whatever doesn't fill at
  once.
- **Preview = fill.** The preview runs the real matching and throws the result away, so what you see and what you get
  come from the same code.
- **Money is set aside.** A waiting buy order holds back shares × limit price of your cash; a waiting sell holds back
  the shares. You can't promise the same dollar or the same share twice. When a buy fills below its limit, the
  difference is released.
- **You can't trade with yourself.** An order that would meet your own waiting order is refused: "You have a sell
  waiting at $41.00. Cancel it first."

### Matching

- **Best price first, then oldest first.** An incoming buy takes the cheapest offer; at the same price, the order that
  has waited longest fills first.
- **Players before the market maker at the same price.** That's how players gradually take over from the market
  maker, which the public exchange depends on.
- **Player to player, the waiting order's price wins.** If you bid $40 and a friend is offering at $38, you pay $38.
- **Against the market maker, always the market maker's own price.** Its price for each share comes from the Milestone
  1 formula (each share priced on its own, soft cap included). Your limit is only a ceiling (for a buy) or a floor (for
  a sale). So a waiting buy at $38 that the market maker reaches overnight at $37 fills at $37, not $38.
- **Partial fills.** An incoming order can fill against several waiting orders and the market maker in turn: say 20
  from a friend at $38.00, then 30 from the market maker at $38.12 to $38.40. Each piece is its own trade row.
- **The market maker isn't a row in the book.** Its prices are worked out on the fly from fair value and what the
  league holds. This keeps the book small and means nothing goes stale when fair values change overnight. The screen
  shows it as one line: "Market maker: sells from $38.12, buys from $36.65."
- **Waiting orders fill when the market maker's price reaches them.** After any trade with the market maker (which
  moves its prices) and after the overnight update (which moves fair values), the book is swept: waiting buys at or
  above its selling price, and waiting sells at or below its buying price, fill against it at its price.
- **Rounding.** Market maker fills round against the player, as now (a buy up to the next cent, a sale down). A large
  order that alternates between friends and the market maker can therefore lose up to a cent per market maker piece.
  Player-to-player fills are whole cents × shares and need no rounding.

### Two people at once

Every order, cancel and sweep in a league takes the league's lock first, so one league handles one thing at a time.
Each takes a few thousandths of a second, so twenty friends will never notice. This is the simplest lock that can't be
wrong. The public exchange (Milestone 6) will need one lock per athlete instead; the functions are written so that is
a change in one place. A test sends 20 orders at the same moment for the last 50 shares on offer and checks that
exactly 50 fill.

### During games

- **The market maker steps out** of an athlete from his team's kickoff until the overnight update has processed that
  game, as in Milestone 1. If the robot is held up, he stays out until it catches up.
- **Players keep trading him with each other.** Market orders and new limit orders work as usual against other
  players' orders.
- **Orders placed before kickoff sleep through the game** (decided). A waiting order placed before
  his kickoff can't fill until the overnight update; it wakes up then and is swept against the new prices. Without
  this, a friend who set a sell at $41 on Sunday morning and went to church could be picked off at $41 by someone
  watching his 3-touchdown first half. Orders placed during the game are live: whoever places them is watching.
  Nothing is written when an order sleeps or wakes; the matching simply skips orders older than the current game's
  kickoff.

### The overnight update and the order book

In order, inside one database transaction per day:

1. Insert the day's stat lines and per-share payouts (shared).
2. Insert each league's dividends for holders at record time.
3. Insert the new fair values and group re-checks (shared); mark the day's games processed. The market maker steps
   back in.
4. Sweep every book in every league against the new prices. Orders that fill are listed in that league's report
   ("Your buy of 40 CMC at $52.00 filled at $49.70 overnight").

Dividends come before the sweep, so an overnight fill never earns that day's dividend; record time is midnight, long
before.

### Limit orders' lifetime

Waiting orders last until filled, cancelled (any time, by their owner), or the league ends (decided). At the end of the
league every waiting order is cancelled, "league over", and no more trades are accepted.

## Dividends, record time and rounding

Unchanged from Milestone 1, now for many leagues:

- **Record time** is midnight Eastern at the start of the game's day. Holdings at that moment are added up from trades
  before it. Because trades are final and stamped by the database clock, nobody can add a trade before a past
  midnight, so a held-up day can be paid later and still be exact.
- **Per share** = points × NFL rate × playoff boost, never negative. Shared by every league.
- **Each holder** is paid shares × per share, rounded once to the nearest cent (`nightly.dividend_cents`, unchanged).
- **Who computes them:** the robot (Python), so the same code that matched the week 7 hand check keeps doing it. It
  reads each league's holdings at record time, works out the cents, and sends the rows to one database function,
  which checks the shares against its own count before inserting. After the day is in, the robot reads the rows back
  and checks them again.
- **A league pays only for days between its start and end dates.**
- **Paid once:** the per-share payout's key (game, athlete) and the dividend's key (league, game, athlete, player)
  make a second payment impossible; running the robot twice changes nothing.

## The nightly robot

- **Where:** a GitHub Actions workflow in the project's repository, free. It runs `tools/nightly.py --online` with the
  Supabase secret key kept in the repository's secret settings. The same command runs on the Mac, reading the key
  from `~/.config/sports-stocks/live.env`.
- **When:** GitHub's timer is in UTC and is often 10-30 minutes late, so it's set for several times each morning
  (about 4:30, 6:30, 9:30 and 12:30 Eastern, adjusted for daylight saving). A run with nothing to do just says so.
  Every run also keeps the free Supabase project from going idle.
- **Stop and pay nothing** on any bad box score, as now, including empty player stats (the 27 Oct lesson). A stopped
  day holds back the days after it.
- **Loud failure (the 27 Oct lesson).** Three layers, because a Mac notification went unnoticed for two days:
  1. A run that stops exits with an error, and GitHub emails you about a failed run (on by default; check it in
     "What you need to do").
  2. The robot writes its status to the database. If yesterday isn't processed by 10 a.m. Eastern, **every player sees
     a banner**: "Overnight update delayed: waiting on DAL at PHI's box score. Dividends will be paid when it arrives."
     This also catches a robot that didn't run at all, which no email would.
  3. A daily self-check: in every league, cash and holdings add up, no one's cash or shares are below zero, every
     order's open shares equal its shares minus its fills, and the market maker holds exactly minus what the players
     hold. A failure stops the robot and emails you.
- **Setting a game aside.** If ESPN never fixes a box score, `python3 tools/nightly.py --online --set-aside GAME_ID`
  (run by you, with a reason) lets the other games pay. The set-aside game is paid later, at its own record time,
  when a good box score arrives (decided).
- **GitHub switches off timed workflows** in a repository with no commits for 60 days. During the beta there will be
  commits; the banner catches it if not.

## Leagues

- **Create:** name, start date (today or later), end date. You get a 6-character code (no 0/O or 1/I to mix up) and a
  link that fills it in. The creator can change the dates before the start and make a new code.
- **Join:** sign in, enter the code, pick a display name. At most 20 players.
- **Before the start date** members can look at prices but not trade.
- **Joining mid-season (decided):** allowed at any time, with the same $100,000. The leaderboard shows "joined week
  N". A late joiner has missed some dividends but also every early mistake.
- **What a new joiner sees:** the market at today's prices (fair values are shared, but each league's market maker has
  its own holdings, so a busy league's prices differ), the leaderboard, a welcome note linking to "How it works", and
  that morning's report.
- **Seeing others:** each player's holdings and trades are visible by name to the league (decided). The order book shows
  prices and share counts **without names** (decided), as real exchanges do.
- **Net worth** stays as decided: cash plus what selling every holding to the market maker would bring, at its
  current prices, even while it is stepped out. Players' bids don't count, so two friends can't raise each other's
  worth with a silly bid.

## Screens

The Milestone 1 screens, with the new pieces:

- **Sign in:** email, then the 6-digit code from the email. You stay signed in on that phone.
- **Leagues:** your leagues, create one, join with a code.
- **Market:** as now, plus the last trade price (the ticker price) and the best bid and offer.
- **Athlete:** the book (top five prices each side, plus the market maker's line), recent trades in this league, and an
  order box: buy or sell, market or limit, shares, price, with the preview. Your open orders on this athlete, each
  with Cancel.
- **Portfolio:** as now, plus cash set aside for waiting orders and a list of your open orders.
- **League:** leaderboard; tap a player to see their holdings.
- **Report:** the league's morning report, including overnight fills.
- **Banner** when the overnight update is late.
- The page checks the book every 5 seconds while it's open and visible (live push can come later); that's well
  inside the free plan.

## Supabase free plan: what matters

Checked 2026-10-28 from third-party summaries; confirm on supabase.com/pricing when you sign up.

| Limit | Free plan | What we'll use |
|---|---|---|
| Projects | 2 active | Both: live and test |
| Database size | 500 MB | Under 20 MB for a season of 20 players (trades, orders, dividends are small rows) |
| Data sent out | about 5 GB a month | Under 1 GB: 20 players checking the book every 5 seconds for an hour a day each |
| Monthly active users | 50,000 | 20 |
| Pausing | after about a week with no activity | The robot touches it several times a day |
| **Sign-in emails** | **The built-in sender only reaches the project's own team, about 2 an hour** | **Must use your own mail sender** (below) |

**Sign-in emails are the one real snag.** Supabase's built-in email is for testing only: friends' addresses are
refused. The free way round is to send through your Gmail: Google gives you an "app password" for this, you type it
into Supabase's settings yourself, and sign-in emails come from your address (Gmail allows about 500 a day). After
that, Supabase allows 30 sign-in emails an hour, which can be raised.

Backups: the free plan doesn't offer downloadable backups. The robot will export each league's trades and dividends
to the Mac when you run the hand check, and the season's shared data is re-creatable from ESPN.

## Testing "two houses"

Before any friend sees it:

1. **Automated, on the test project:** every rule above has a test (list in step 2), plus the 20-orders-at-once test
   and the Python/SQL price agreement test.
2. **You alone, two devices:** your phone on mobile data (not your Wi-Fi) and your laptop, signed in with two email
   addresses you own, in a test league on the real site. A checklist walks you through it: a limit sell on one, see it
   on the other, fill it, cancel one, a market order that only partly fills, a sleeping order across a
   real game.
3. **The real two houses (the "done when"):** you and one person at their own house (family is fine), 30 minutes, the
   same checklist, then the next morning's hand check. A short tester survey goes with it.

## What can slide to the beta

Fits in the five weeks (in order of importance): the database rules and matching, the robot online with its alert,
sign-in and leagues, the athlete screen with the book and order box, the leaderboard and others' holdings, GitHub
Pages, the two-house test.

If time runs short, these move to Milestone 3 in this order (last first): adding to the home screen (icon and
manifest), the league part of the morning report (the shared part stays), the "set aside a game" command, recent
trades on the athlete page.

Not in Milestone 2 at all, but **needed before the beta starts:**

- **NBA and NHL** adapters, listings and catch-up (Milestone 3's main job). They don't depend on any of this and could
  be built alongside in a separate conversation from week 2 if usage allows.
- **Should fair value fall as a season runs out?** A December-to-March league crosses the end of the NFL regular season
  (week 18 ends 3 Jan 2027). Without it, NFL prices stay high into January while most athletes have nothing left to
  pay.
- **WR/TE has paid 114% of its promise two weeks running.** Recheck after weeks 8 and 9.
- **Option B of `research/AVAILABILITY_CURVE.md`** (the curve in prices too) waits for a 2024 check that needs new
  ESPN downloads: your OK first.
- **Stat corrections:** still paid once at the time of the run.

## The shortcut for family in weeks 9-10 (optional)

A "who's playing" picker on the Mac's local server so family can trade on home Wi-Fi before the online pieces exist.

- **Cost:** about one Sonnet conversation: a picker, more than one player in the save, the hand check listing each
  player.
- **What it gives:** family's reactions to the screens and the economy a month earlier, and a second survey.
- **What it doesn't:** no order book; everyone trades only with the market maker (the shared one, so family would push
  each other's prices). Nothing of the online pieces gets tested.
- **Thrown away afterwards:** the picker and the local multi-player bits. The save and its hand check stay as records.

**Decided 2026-10-28: not doing it.** Instead the full build starts now; anything week 8 turns up is fixed in the
live game as we go.

## Order of work

Week numbers start Thu 29 Oct.

| Step | Week | What | Suggested model |
|---|---|---|---|
| 0 | 1 | **You:** accounts and keys (next section); play week 8 and answer the survey. Claude starts step 1's offline parts (schema, migration tool, key script) at once | (you) |
| 1 | 1-2 | Repository on GitHub; `db/migrations/` and `tools/db.py`; shared and per-league tables; row-level security; final-trades and final-dividends triggers; copy the season so far (athletes, schedule, stat lines, payouts, fair values, re-checks) from the Mac save to both projects; tests that phones can't write anything | Opus medium |
| 2 | 2 | Market maker prices in SQL, agreeing with Python on thousands of cases and every real trade; orders, matching, cancel, sleeping orders, sweep, preview, leagues and joining; a test for every rule in "The order book's rules", the 20-at-once test | Opus medium |
| 3 | 3 | **Review of the matching rules and code:** a fresh conversation reads this plan's rules and step 2's code and tries to break them (money created or lost, two people taking the same shares, a stuck order, a preview that differs from its fill). Fixes before anything else builds on it | **Opus high** |
| 4 | 3 | Robot online: `nightly.py --online`, dividends sent and read back, sweep, reports, status row and banner data, the daily self-check, GitHub Actions workflow, failure email; hand check reading from the database; three clean nights on the test project, then switch the Mac's 4:00 job off | Opus medium |
| 5 | 4 | Screens: sign-in, leagues, the order box and book, open orders, leaderboard, others' holdings, banner; week 8 survey findings folded in as they arrive (not waited for) | Sonnet medium |
| 6 | 4 | GitHub Pages; adding to the home screen; checked at phone size in the Browser pane | Sonnet medium |
| 7 | 5 | Two-house test with a checklist and a tester survey; fix what it finds (Opus for any money bug) | Sonnet medium |

Steps 1 to 4 move play money and decide what the database allows, so they stay on Opus. Each step starts in a new
conversation from a short handoff brief, to keep conversations short.

## What you need to do

Claude never sees a password or a secret key. Where a secret has to go on the Mac, you'll run a small script that
asks for it without showing it and saves it in `~/.config/sports-stocks/`, readable only by you.

**Before step 1:**

1. **GitHub.** Sign up at github.com if you don't have an account (free). Create an empty repository called
   `sports-stocks`, **public** (free GitHub Pages needs that; see decisions), with no README. Tell me your GitHub
   username. Then, in a terminal, sign in so the Mac can push (I'll give you the one command; it opens your browser).
2. **Supabase.** At supabase.com, "Start your project", sign up with GitHub. Create two projects, `sports-stocks` and
   `sports-stocks-test`, region "East US". Each asks for a database password: let it generate one and keep it in your
   password manager. We won't need it.
3. **For each project**, from Project Settings, API Keys:
   - The **project URL** and the **publishable key** (older screens call it "anon"). These are meant to be public;
     paste them in chat or a file, either is fine.
   - The **secret key** (older screens: "service_role"). Never in chat. Run `python3 tools/set_key.py live` (or
     `test`) and paste it at the prompt.
4. **A personal access token** at supabase.com/dashboard/account/tokens, named "sports-stocks Mac". Run
   `python3 tools/set_key.py token` and paste it at the prompt. You can revoke it after Milestone 2.

**Before step 4:**

5. **GitHub secrets:** in the repository, Settings, Secrets and variables, Actions, add `SUPABASE_URL` and
   `SUPABASE_SECRET_KEY` for the live project (paste them there yourself).
6. **Failure emails:** github.com/settings/notifications, Actions: make sure email is on for failed workflows.

**Before step 5:**

7. **Gmail app password:** turn on 2-Step Verification for your Google account if it isn't, then create an app password
   at myaccount.google.com/apppasswords called "Sports Stocks".
8. **Supabase mail settings** (live project): Authentication, then Emails, SMTP settings: on; host `smtp.gmail.com`,
   port 465, username your Gmail address, password the app password, sender name "Sports Stocks". Then
   Authentication, Rate limits: emails per hour 30. I'll give you the sign-in email's wording to paste into the email
   template (it shows the 6-digit code).

**Before step 6:**

9. **GitHub Pages:** repository Settings, Pages, Source: "GitHub Actions". The site will be
   `https://<username>.github.io/sports-stocks/`.

**Step 7:** line up one person in another house for 30 minutes.

## Downloads I'll need your OK for

1. **The Supabase JavaScript library** (supabase-js, one file of about 150 KB, from jsdelivr.net), saved in
   `web/vendor/` at a fixed version so the site never changes underneath us. It handles sign-in and staying signed in.
   The alternative is writing those requests by hand (more code to get wrong).
2. Nothing else: the ESPN NFL schedule and box scores are already covered by your standing OK.

## Decisions (answered by Justin, 2026-10-28)

1. **Orders placed before kickoff sleep through the game** and wake at the overnight update. Yes (default).
2. **Market orders fill what's on offer** and tell you how many you got; the rest is dropped. **Changed from the
   default** (all or nothing). The price guard still applies; see "Orders".
3. **Limit orders last until cancelled or the league ends**, and their owner can cancel any time. Yes (default).
4. **The order book shows prices and share counts without names**; holdings and trades show names. Yes (default).
5. **Late joiners start with $100,000, any time.** Yes (default).
6. **Sign-in by a 6-digit code emailed from your Gmail.** Yes (default).
7. **The code is public on GitHub**; box scores, saves, check workbooks and the economy workbook stay off it. Yes, for
   now (default).
8. **Database changes through a personal access token** kept on the Mac. Yes (default).
9. **The supabase-js download.** Yes (default).
10. **"Set aside a game"** command. Yes (default).
11. **No family shortcut.** Start the full build now instead; if week 8 turns something up, adjust it live.
12. **Week 8 survey:** step 5 no longer waits for it; findings are folded in as they arrive.

## Progress

**2026-10-28, step 1's offline half** (no accounts needed; nothing has touched the internet yet). 48 tests pass
(`python3 tests/run.py`; 7 new).

- `tools/set_key.py`: saves a project's URL and secret key, or the access token, in `~/.config/sports-stocks/`
  without showing them.
- `engine/online.py`: the robot's and tools' door to Supabase (web API with the secret key; management API with the
  token), standard library only.
- `tools/db.py test|live status|push|reset`: applies `db/migrations/` in order, each all or nothing, and runs a
  safety check: every table has row-level security, phones can't write to any table, and phones can call only the
  functions in `db/phone_functions.txt` (none yet).
- `db/migrations/001_shared.sql`: seasons, athletes, groups, re-checks, games, stat lines, payouts, fair values, robot
  status. Stat lines and payouts are final.
- `db/migrations/002_leagues.sql`: markets, members, orders, trades, dividends, reports, and who may read what. Trades
  and dividends are final; an order can only be filled down or closed, never reopened or deleted; a trade's buyer and
  seller must belong to its league.
- `tools/upload_season.py test|live`: copies the shared season from the Mac save (120 athletes, 272 games, 653 stat
  lines and payouts, 2,640 daily fair values through 26 Oct) and reads it back to check every value matches exactly.
  Online ids carry the season: `nfl-2026:3117251`.
- `tests/test_migrations.py`: the same lock-down checks on the SQL files, plus the uploader's rows fitting the tables.

**Not yet run against Supabase.** The SQL has never been executed; the first `python3 tools/db.py test push` will show
any mistakes. Next: your accounts and keys, then the online half of step 1 (push, safety check, upload, a test that a
signed-in phone can't write), then step 2.
