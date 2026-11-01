# Two-house test (Milestone 2, step 7)

This is Milestone 2's "done when": two phones in different houses trade with each other and with the market maker, and
both see the same book. It takes about 30 minutes, plus a few minutes the next morning.

**Site:** https://iamjgw.github.io/sports-stocks/ . Until the switch to live, it uses the test project, so the league
is play money on the bench and the data isn't kept.

## Before you start

- One person at their own house, on their own phone, on their own internet. Be on a call together.
- You on your phone on mobile data, not your home Wi-Fi.
- Pick a time with **no NFL game on** for the first half. Do the "sleeping order" part before a real game.
- Have the survey ready: `playtest/out/sports-stocks-two-houses.html`, and the text version for them.

## 1. Getting in

- [ ] They open the site and sign in with an address never used here. The email arrives and shows a **6-digit code**.
      Note how long it took and whether it went to spam.
- [ ] You create a league, tap **Share link** and text it to them.
- [ ] They open the link, type a display name and join. They see the league.
- [ ] Both of you add the site to your home screen (iPhone: Share, then Add to Home Screen). The icon is three white
      bars on blue. **On iPhone the home-screen copy keeps its own sign-in, so expect to sign in once more there.**

## 2. Trading (the part that must pass)

Both open the same athlete's page and stay on it.

- [ ] **You:** a limit sale a little below the market maker's price. **Them:** it appears within 10 seconds without
      touching anything.
- [ ] **Them:** a market buy that fills your order. **You:** within 10 seconds your open order goes, and the trade shows
      their name.
- [ ] Swap roles and do both again.
- [ ] Both open the League tab: both players on the leaderboard, and tapping one shows their holdings.
- [ ] **One of you:** a limit order, then Cancel it. It leaves the other's book within 10 seconds.
- [ ] **One of you:** a market order bigger than your cash. It fills part and says how many weren't ordered.
- [ ] **Both:** open the Market screen and find the athlete you traded: last trade, bid and offer look right.

## 3. Sleeping order (spread over a real game)

- [ ] Before kickoff, place a limit order on a player in that game. During the game it shows as asleep, and the market
      maker says he's out.
- [ ] The next morning it has filled or is awake, and the Report says so if it filled.

## 4. The next morning

- [ ] Both open the **Report**: the day's games, dividends, anything filled overnight.
- [ ] Run the hand check for each player and read Mismatches at the top. It must say 0:

```bash
python3 tools/hand_check.py --online --target test --league CODE --player "Your name"
```

- [ ] Both fill in the survey, then paste the answers into a Sports Stocks conversation with Claude.

## If something goes wrong

Write down what you each saw and the time. **Any wrong money number: stop and bring it to an Opus conversation**,
with the league code, before trading further. The trades are final, so the record stays exactly as it happened.
