# Market Scanner (paper trading)

Rule-based screens, not financial advice. Paper-trade for 2-3 weeks before using money.

| Job | When | What |
|---|---|---|
| `intraday` | every 5 min, 9:15-15:30 IST (run inside the `monitor` job) | NIFTY option signal + live scan of the 80 most-traded F&O stocks (Yahoo 5-min data, option premium estimated from NSE's daily IV); paper-trades signals to target/stop/15:15 |
| `monitor` | 9:15-15:31 IST, loops every 30 s | **NIFTY paper engine**: opening-range breakout signal, fills at ask (limit, may go unfilled), exits at validated NSE bid, append-only `data/ledger.jsonl`, trades in `data/engine_trades.csv`, quote recording in `data/quotes/` |
| `daily` | 19:00 IST | grades yesterday's picks, next-day CE/PE picks across F&O stocks, long-term watchlist |

Dashboard: `docs/index.html` - tabs: Today (beginner view), NIFTY, Stock movers, Tomorrow's ideas, My results, Long-term, Learn.
File: (rebuilt after every job, auto-refreshes every 5 min).

## Local commands
```
cd "/Users/srimouni/My Data/nifty-scanner"
PY=~/.venvs/nifty/bin/python
$PY app.py open            # open dashboard in browser
$PY app.py report          # results in terminal
$PY app.py monitor         # NIFTY engine for the session (keep running 9:15-15:31)
$PY app.py engine-report   # expectancy, drawdown, slippage, data problems
$PY app.py intraday --force
$PY app.py daily
$PY app.py test-notify     # Mac / Telegram / WhatsApp check
```
Mac schedules: `~/Library/LaunchAgents/com.srimouni.nifty-scanner.plist` (intraday) and
`com.srimouni.market-daily.plist` (daily). Stop: `launchctl unload <file>`.

## Messages
Put secrets in `.env` (copy `.env.example`). Which alerts go where is set in `config.json -> notify`:
`"all"` = every 15-min update, `"signals"` = buy/exit/daily picks only, `"off"`.

**WhatsApp (CallMeBot, free, personal):** get CallMeBot's current WhatsApp number from
https://www.callmebot.com/blog/free-api-whatsapp-messages/, save it in your contacts, send it
"I allow callmebot to send me messages". It replies with an API key.
Set `WHATSAPP_PHONE=+91...` and `CALLMEBOT_APIKEY=...`.
(Twilio also supported - fill the TWILIO_* values instead.)

**Telegram:** message @BotFather -> `/newbot` -> copy token. Send your bot any message, then open
`https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.

## Hosting on GitHub (laptop can be off)
1. `brew install gh && gh auth login`
2. In this folder: `git init && git add . && git commit -m init && gh repo create market-scanner --public --source . --push`
3. Repo Settings -> Secrets and variables -> Actions: add the same keys as `.env`.
4. Settings -> Pages -> Deploy from branch `main`, folder `/docs`. Put the URL in `config.json -> dashboard_url`.
5. Actions tab -> run `intraday` and `daily` once by hand to check NSE allows GitHub's servers.
6. Then turn off the Mac jobs (`launchctl unload ...`) so both don't run.

Notes: GitHub's scheduled runs can start 5-15 min late. NSE may block cloud servers -
if the intraday job fails there, keep intraday on the Mac and host only `daily`.

## Reliability rules (NIFTY engine)
- Quotes rejected if NSE timestamp > 3 min old, bid/ask missing, crossed, or spread > 1%.
- Buy = limit at the signal's ask; fills only if the ask is still <= limit within 2 min (+1 tick slippage), else UNFILLED.
- Exit = validated bid, every 30 s. If quotes are bad at 15:15, exits at the last valid bid and says so.
- State is written atomically; a position left from an earlier day is recorded as MISSED, never dropped.
- The old 3-vote NIFTY rule is info-only (`intraday.open_trades: false`). Stock scanner is separate and experimental
  (stock-option results are model estimates).
