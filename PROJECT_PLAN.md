# Sports Stocks (was Stat Street): project plan

Name for now: Sports Stocks. Started 2026-10-16. This is a separate project from Cold Cells, the Bible game and Ember Reach; keep its
files in `sports-exchange/`.

## The idea in one paragraph

A fantasy sports game dressed as a stock exchange. Every listed athlete, across several sports, is a stock with a
ticker. Each player starts with the same pile of play money and buys and sells shares, either from the game's own
market maker or from each other through an order book. When an athlete plays, his stat line is turned into a
**dividend** paid to everyone holding his shares, and his share price moves with how well he's playing and how much
the market wants him. It starts as a league of up to 20 friends who join with a short code; whoever has the highest
net worth (cash plus shares) when the season ends wins. The long-term goal is one big public exchange with thousands
of players, where prices are set almost entirely by the players themselves.

## Design pillars

1. **It should feel like a market, not a draft.** Prices move, you can buy low and sell high, and timing matters.
   Nobody "owns" an athlete exclusively; three friends can all hold the same star.
2. **Every sport pulls its weight.** A season of an average NBA starter should be worth roughly the same as a season
   of an average NFL starter, even though one plays 82 games and the other 17. Sport choice is a strategy, not a trap.
3. **Works for daily and casual players alike.** Some friends will check in daily, others a few times a week. Orders
   that wait in the book, a daily market report, and portfolios that keep earning while you're away mean nobody falls
   hopelessly behind for checking in less.
4. **Built to grow.** A friends league and the future public exchange are the same thing at different sizes: a market
   with its own order book. The game's market maker is the training wheels; as more players trade, it steps back.
5. **Bragging rights only.** Play money, no entry fees, no prizes paid through the app. Real-money fantasy games are
   regulated state by state; we stay well clear of that. (A side bet between friends is their business, outside the
   app.)
6. **Zero cost to run**, at least through the friends stage: free hosting, free data, no credit card anywhere. The
   public stage may change this; see the roadmap.

## How it plays (first pass)

**Sports at launch:** NFL, NBA and NHL, all in season through the winter. MLB is added for Opening Day 2027.

**Listing.** Not every athlete is tradeable: roughly the top 100–150 per sport (starters and notable bench players),
each with a short ticker (MAHOM, JOKIC, MCDAV). Rookies and breakout players can be "IPO'd" mid-season.

**Starting out.** Everyone gets the same play money, say $100,000, and the same starting prices, set from each
athlete's production last season.

**Dividends.** After each game, the athlete's stat line is scored with standard fantasy points for his sport, then
multiplied by that sport's dividend rate. The rate is what makes sports comparable: sports with more games get a
smaller rate per game.

> Example (numbers are placeholders until the economy workbook sets them): you own 100 shares of a quarterback at
> $50. He throws for 300 yards and 3 touchdowns, worth 24 fantasy points. At an NFL rate of $0.05 per point per share,
> you're paid $1.20 a share, or $120. An NBA player scoring the same fantasy points pays much less per game because he
> plays about five times as often.

**Record time.** Dividends for a day's games go to whoever held the shares when that day began (midnight Eastern).
Buying a player halfway through a game he's dominating doesn't earn you that game. This is the same idea as a real
stock's "record date", and it lets us update stats once a night instead of live.

### The market: market maker plus order book

Each league is its own market with one order book per athlete. Two kinds of traders fill it:

- **Players** place orders. A *market order* buys or sells right now at the best price available. A *limit order*
  names a price ("buy 50 JOKIC if it drops to $38") and waits in the book until someone takes it or it's cancelled.
  Limit orders are what let a casual player set things up on Sunday and walk away for the week.
- **The market maker** is a computer trader run by the game. It always posts a price it will buy at and a slightly
  higher price it will sell at, so there's someone to trade with even when no friend is online.

**Who trades with whom.** Every order fills at the best price in the book, whoever posted it. When a friend's limit
order beats the market maker's price, friends trade with each other; otherwise the market maker takes the other side.
In a quiet 8-person league most trades will be with the market maker. In a busy public market, players will undercut
it constantly and it becomes a backstop.

**How the market maker sets its prices.**
- It starts from **fair value**: what the athlete is expected to pay out, based on recent production. Updated nightly.
  A hot streak lifts it; an injury or slump drags it.
- It then leans on **its own stock pile**. If players have been buying an athlete from it, it raises its prices; if
  they've been selling to it, it lowers them. This is how "everyone wants him" moves the price even when friends
  aren't trading directly with each other.
- **It steps out during games.** From an athlete's game start until the overnight update, the market maker stops
  quoting him (or quotes a very wide gap). Otherwise anyone watching a 50-point night could buy from it at yesterday's
  price before fair value catches up. Players can still trade him with each other during the game, which is where
  some of the most exciting trading will happen.
- **It shrinks as the market grows.** The gap between its buy and sell prices, and how many shares it offers, are
  settings. A friends league gets a generous market maker; the public exchange gets a thin one.

**The ticker price** shown on screen is the last trade price, whoever made it.

**Scoring.** Net worth = cash + every share valued at the best price someone would pay for it right now. Valuing at
the buy-side price matters: otherwise someone could pump one athlete's price and look richer than they are.

**The daily rhythm.**
- Overnight (around 4 a.m. Eastern) a scheduled job fetches yesterday's box scores, pays dividends, updates fair
  values, re-centres the market maker, and writes a short **market report**: top gainers and losers, biggest
  dividend, busiest stocks, who made the big moves.
- During the day, trade whenever you like. Waiting limit orders fill automatically when the price reaches them.

**Seasons.** The league creator picks start and end dates (say, December to March), so a group can run several
seasons a year. An athlete whose sport is out of season pays nothing, so his price tends to slide; holding him into
next season is a legitimate, cheap bet.

**Later ideas** (not in the first version): short selling, price charts, achievements ("Diamond Hands": held one stock
all season), a weekly email digest, more sports.

## How it's built: decisions and why

Same approach as the other games: plain web pages and JavaScript, no build tools, nothing to install on the Mac.

- **A website that works on phones**, installable to the home screen. No app stores. Hosted free on **GitHub Pages**.
- **Supabase free plan** for the shared parts: sign-in (a link emailed to you, no passwords to remember), the database
  of leagues, portfolios, orders and prices, and the trading rules. Matching orders, paying dividends and moving cash
  all run *inside the database*, on the server, so nobody can give themselves extra money by tinkering with their
  browser, and two people can't both buy the last share at once. No credit card needed.
  - Why not Firebase, which Ember Reach uses: Firebase's free plan can't run code on the server without a card on
    file, and in this game the server has to be the referee for every trade and dividend.
  - Every league is a "market" in the database. The public exchange later is just one very large market, so the same
    code serves both.
- **A free nightly robot (GitHub Actions)** runs the overnight job: fetch box scores, pay dividends, update fair
  values. It's written in Python with no add-ons, so the same script also runs by hand on Justin's Mac for testing.
- **Stats from free public feeds**: ESPN's public scoreboard and box-score feeds cover NFL, NBA and NHL (and MLB
  later); the NHL also publishes its own free feed as a backup. These are public but unofficial and can change without
  warning, so all fetching lives in one small "data adapter" per sport that we can swap out.
- **The economy lives in a spreadsheet first.** Dividend rates, starting prices and the market maker's settings are
  tuned in an Excel workbook using last season's real stats before any of it is coded, and the code reads its numbers
  from that same table. That puts the balance work where Justin is strongest.

## Roadmap

Timing note: it's mid-October 2026. NFL, NBA and NHL are all in season through the winter; MLB returns in late March
2027. Getting a friends beta running by December catches the heart of three seasons.

| # | Milestone | What's in it | Done when | Suggested model |
|---|---|---|---|---|
| 0 | Decide and model | Confirm the free data feeds work for NFL, NBA and NHL; build the economy workbook from last season's stats, including a simple market maker; pick a name | The workbook shows each sport paying a similar season return, and a simulated season has a believable spread of winners | Opus high |
| 1 | Solo prototype | NFL only, listed athletes, buying and selling against the market maker, portfolio screen, the nightly job run by hand on real box scores, all on Justin's Mac | Justin "plays" a week of real NFL games and the dividends match a hand check in the workbook | Opus medium for the money logic; Sonnet medium for screens |
| 2 | Online league | Sign-in, create a league with a join code, the order book (market and limit orders matched on the server), market maker stepping out during games, leaderboard, market report, nightly robot, hosting on GitHub Pages | Two phones in different houses trade with each other and with the market maker, and both see the same book | Opus medium; Opus high to review the matching rules |
| 3 | Friends beta | NFL, NBA and NHL; invite 5–8 friends for 2–3 weeks, then open it to the full group of up to 20 | Friends play without help, and a week of trades and dividends survives a hand audit | Sonnet medium, Opus for any balance or money bug |
| 4 | More sports and depth | MLB by Opening Day 2027, price charts, IPOs, achievements, email digest | A full league season runs start to finish | Opus high to design new mechanics, Sonnet to build |
| 5 | Polish | How-to-play guide, look and feel, notifications | A new friend joins from a link and understands it in five minutes | Sonnet medium |
| 6 | Public exchange | One big open market; thinner market maker; protection against one person running several accounts; terms of use and privacy page; a licensed stats source if the free feeds don't allow public use; load testing | Hundreds of strangers trade for a full season without the market maker propping it up | Opus high; this stage may need a small budget (see risks) |

## Who does what

- **Justin:** the rules and the economy workbook; checking that dividends and prices "feel right"; recruiting friends;
  judging what's fun. He also creates the free accounts (GitHub, Supabase), since those need his own sign-up.
- **Claude:** the code, the data adapters and nightly job, the order matching and database rules, and explaining each
  step in plain terms with exact commands to run.

## Decided (2026-10-16)

- Sports at launch: NFL, NBA, NHL. MLB for Opening Day 2027.
- Market: a computer market maker plus a player order book, in the same market. Long term, a public exchange where
  players set nearly all prices.
- Season length: dates the league creator picks.
- First league: up to 20 friends, some checking daily, some a few times a week.

## Milestone 0 progress (2026-10-16)

The economy workbook is `Stat Street Economy.xlsx`. `tools/fetch_season_stats.py` downloads the stats and
`tools/build_economy_workbook.py` rebuilds the workbook. Prices are set from one season (NFL 2024; NBA and NHL 2024-25)
and dividends are paid from the next (2025 / 2025-26), which is how a real league would play out. Default levers:
$100,000 starting cash, $50 average starting price, 2% weekly dividend yield, 120 NFL / 150 NBA / 150 NHL athletes
listed.

- **Scoring:** half-PPR for the NFL (QB, RB, WR and TE only); FanDuel-style for the NBA; for the NHL, goals 3,
  assists 2, shots 0.5, with goalie weights tuned so about 33 goalies are listed. The free feed has no hits or blocked
  shots, so NHL defencemen score low.
- **Pricing rule:** in every sport the average athlete starts at the target price and is expected to pay the weekly
  yield. Normalizing by week rather than by season means a dollar earns at the same speed in every sport.
- **Sport balance holds up.** Share of the target weekly yield actually paid: NFL 79%, NBA 85%, NHL 91%. All three
  come in under 100% because great seasons tend to be followed by ordinary ones. The NFL trails a little, mostly
  because of quarterbacks (74%).
- **NHL goalies were a problem.** Under one price rule for everyone, they paid only 50% of their target, against
  about 100% for skaters. Goalie output swings a lot from year to year and starters lose their jobs.
- **Fix (decided 2026-10-17): position groups.** Each group gets two factors, set by `tools/calibrate.py` from older
  seasons. The groups are NFL QB, NFL RB, NFL WR/TE, NBA, NHL skaters and NHL goalies.
  - *Lean toward the group average* prices a star a bit below his last season and a weak player a bit above,
    because part of any season doesn't repeat.
  - *Repeat factor* folds in games missed and how much the group tends to fall back.

  One dividend rate per sport still applies, so a point is worth the same to everyone in a sport. Goalies now cost
  about $28 on average, against $56 for skaters.
- **Balance goal (Justin, 2026-10-17):** when sports overlap, putting all your money in one sport should be no better
  than spreading it. Honest test (factors set on one pair of seasons, checked on the other): no sport came out ahead
  in both years, and which sport paid most flipped from year to year (NFL 91% / 106%, NBA 89% / 112%, NHL 101% /
  99%). Goalies moved from 50% to 90% / 111% of target, against skaters' 104% / 95%. On the workbook's seasons, with
  the averaged factors: NFL 94%, NBA 94%, NHL 100%; groups run from 91% to 102%.
- **One season can't remove the luck.** A sport can still run about 10% hot or cold in a given year. In the live
  game, the market maker should therefore re-check each group's repeat factor every week against the dividends it
  has actually paid that season. A hot or cold group gets re-priced as the season goes, instead of staying an easy
  buy. This goes into Milestone 1's market-maker rules.
- **Season sim:** 20 friends each buy 10 athletes and hold them for 18 weeks. Results run from −8% to +37%
  (median +23%), and dividends add up to about 34% of everyone's starting cash. That's a healthy spread. The averages
  by strategy are too noisy to trust with three friends per strategy.
- **Pumping a price doesn't pay, but it can look like it does.** Buying 1,000 shares of one athlete from the market
  maker shows a 1.4% paper gain at the quoted sell price, but selling it all back loses 3.0%. Decision: value
  holdings at what selling all of them would bring in.
- **Dividends never go negative.** A bad game pays zero; it never charges the holders.
- **Data feeds:** ESPN's public feed works for all three sports. Its NFL list leaves out players who weren't
  "qualified" (often injured ones), so those players are looked up one by one.

## Decided (2026-10-18): Milestone 0 answers

1. **Starting cash: $100,000** (Justin: "whatever you think"). **No hard cap** on shares of one athlete; going all in
   is allowed. Instead a **soft cap**: the market maker's price climbs as the market holds more of an athlete, so
   cornering one is very expensive. Milestone 1's plan sizes this in dollars per step.
2. **Players can see what other players hold** (the spread of athletes in each portfolio), not just the leaderboard.
   Built in Milestone 2.
3. **Playoff games pay boosted dividends** (a playoff multiplier lever). Still open: whether fair value should fall as
   a season runs out; needed before the friends beta, not for Milestone 1.
4. **Name: "Sports Stocks"** for now (may change later). "Stat Street" stays as the folder's old working title.

Milestone 0 is done. Milestone 1's plan is `MILESTONE_1_PLAN.md`.

## Risks and what we do about them

| Risk | What we do |
|---|---|
| A free stats feed changes or disappears | One adapter per sport with a backup source; the nightly job alerts us instead of paying wrong dividends |
| One sport turns out to be the "obvious" pick | Position-group factors set from past seasons; the market maker re-checks them weekly in season; re-calibrate each year with the new season's data |
| Someone games the market (buying mid-game from the market maker, pumping a price) | Record time at midnight, market maker steps out during games, net worth valued at the buy-side price, holding cap |
| The market maker is too generous (easy free money) or too stingy (nothing to trade with) | Its gap and depth are workbook settings; we simulate a season against it before the beta and watch it during the beta |
| Order-matching bugs move money wrongly | Matching runs in one place on the server; every trade is logged; the beta includes a hand audit; Opus reviews this code |
| Supabase pauses free projects after a week with no activity | The nightly robot touches it every day, so it never goes idle |
| Friends drift away | Limit orders, the daily market report, and portfolios that keep earning while you're away |
| The public stage outgrows free tools | Free feeds may not permit public use, and thousands of users may exceed free limits; we decide at Milestone 6 whether to pay for data or hosting, with real usage numbers in hand |
| Scope creep (thousands of athletes, ten sports) | Listed athletes only, three sports at launch |

## Next step

Milestone 1 steps 1 to 4 are built (see `MILESTONE_1_PLAN.md`, "Progress"). Next: the screens (step 5) and the
hand-check workbook (step 6), then Justin plays a real week. Open question from the build: the early-season NFL
groups pay well above their promise; checking whether that's a pattern needs 2025's weekly box scores.

## Next step (2026-10-28)

Milestone 1 is built and running: the nightly job has paid 107 NFL games through week 7, and week 7's dividends
matched the hand check (83 lines). Justin trades through week 8 (29 Oct-2 Nov) and answers the week's survey.

Milestone 2, the online league, is planned in `MILESTONE_2_PLAN.md`: trading and the order book inside Supabase, the
nightly robot on GitHub Actions, about five weeks to a two-house test in early December. It waits on Justin's answers
to its "Decisions for you" and on his GitHub and Supabase accounts.
