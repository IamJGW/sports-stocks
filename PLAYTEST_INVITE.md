# Inviting playtesters

## Before you send it (5 minutes, once)

1. Open https://iamjgw.github.io/sports-stocks/ and sign in with your email.
2. Tap your league name at the top (or **Leagues**). Under **Create a league**, give it a name and your display name.
   **Set the end date a few weeks out**, not days: test runs on the test database can close a league that ends within
   about three days.
3. On your new league, tap **Share link**. It copies a link like `https://iamjgw.github.io/sports-stocks/?join=ABC234`.
   Paste it into the message below where it says `[JOIN LINK]`.

Up to 20 players per league. Sign-in emails are limited to about 30 an hour, so invite people in batches if you're
sending to more than 20 at once.

## The message to send (copy everything inside the box)

```text
Want to try a game I'm building? Sports Stocks: NFL players are stocks. Buy and sell shares with play money
($100,000 to start), and every time your players play, their stats pay you dividends. Highest net worth wins.
No real money, ever.

How to join (2 minutes, best on your phone):
1. Open this link: [JOIN LINK]
2. Type your email and tap "Send code".
3. Check your email for a 6-digit code from Sports Stocks (look in spam if it isn't there in a minute).
   Type it in and tap "Sign in".
4. Pick a display name and tap "Join". You're in.

How to play:
- Market tab: tap any player to see his price. Pick Buy, type a number of shares, check the cost, tap Buy.
- "Limit" lets you name your own price; the order waits until someone matches it. Cancel it any time.
- During his game a player's price is frozen; trading picks up the next morning.
- Each morning after games: dividends land in your cash, and the Report tab shows who earned what.
- League tab: the leaderboard, and what everyone owns.
- The "?" buttons and the "How it works" tab explain the rest.

iPhone tip: in Safari tap Share, then "Add to Home Screen" for an app icon. You'll sign in once more there.

This is a test season: in a couple of weeks the game moves to its permanent home and leagues start fresh.
After a few days of playing, please fill in a 5-minute survey: https://iamjgw.github.io/sports-stocks/survey.html
```

## The survey

https://iamjgw.github.io/sports-stocks/survey.html (already in the message above). Testers tap **Copy my answers** at
the end and paste them to you in a text. If someone would rather not use the page, paste
`playtest/out/sports-stocks-friends-first-look.txt` into a message instead; they type answers under each question.

The page is a copy of `playtest/out/sports-stocks-friends-first-look.html`: after changing the survey, run
`python3 playtest/build.py` and copy it to `web/survey.html` again.

When answers come back, paste them into a Sports Stocks conversation with Claude.
