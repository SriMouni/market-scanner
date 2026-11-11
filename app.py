#!/usr/bin/env python3
"""Market scanner - one entry point for local runs, launchd and GitHub Actions.

  python app.py intraday [--force]   NIFTY 15-min scan (skips outside market hours)
  python app.py daily                end-of-day: grade picks, next-day options, long-term
  python app.py dashboard            rebuild docs/index.html
  python app.py open                 rebuild + open the dashboard in your browser
  python app.py monitor              NIFTY paper engine: 30-s exit watch + opening-range breakout (market hours)
  python app.py brief [--send]       morning "what to buy today" message (auto at 9:35 AM)
  python app.py engine-report        expectancy, drawdown, slippage, rejected quotes, by hour/expiry/IV
  python app.py live                 live server at http://127.0.0.1:8765 (prices every 30-60 s)
  python app.py report               print paper-trading results
  python app.py test-notify          send a test to Mac / Telegram / WhatsApp
"""
import subprocess
import sys

import dashboard
import notify
from common import log, now_ist


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    try:
        if cmd == "intraday":
            import scanner
            import stocks
            force = "--force" in args
            ran = False
            try:
                ran = scanner.run(force=force)
            except Exception as e:  # NIFTY (NSE) failing must not stop the stock scan
                log(f"ERROR nifty scan: {e!r}")
                notify.notify("NIFTY scan error", str(e)[:180], level="signal")
            if ran or (force or scanner.market_open(now_ist())):
                try:
                    ran = stocks.run() or ran
                except Exception as e:
                    log(f"ERROR stock scan: {e!r}")
            if ran:
                dashboard.build()
        elif cmd == "daily":
            import daily
            daily.run()
            dashboard.build()
        elif cmd == "dashboard":
            print(dashboard.build())
        elif cmd == "open":
            path = dashboard.build()
            import urllib.request
            try:  # prefer the live server if it's running
                urllib.request.urlopen("http://127.0.0.1:8765/live.json", timeout=2)
                subprocess.run(["open", "http://127.0.0.1:8765/"])
            except Exception:
                subprocess.run(["open", str(path)])
        elif cmd == "monitor":
            import engine
            engine.run_monitor(once="--once" in args)
        elif cmd == "brief":
            import brief
            title, body = brief.send() if "--send" in args else brief.build()
            print(title + "\n" + body)
        elif cmd == "engine-report":
            import engine
            engine.report()
        elif cmd == "live":
            import live
            dashboard.build()
            live.serve()
        elif cmd == "report":
            import scanner
            from common import DATA, read_csv
            scanner.report()
            rows = [r for r in read_csv(DATA / "daily_results.csv") if r["result"] in ("TARGET", "STOP", "CLOSE")]
            if rows:
                nets = [float(r["net_pnl"]) for r in rows]
                print(f"Next-day picks: {len(rows)} graded, win rate "
                      f"{sum(n > 0 for n in nets) / len(rows) * 100:.0f}%, net ₹{sum(nets):,.0f} (1 lot each)")
            else:
                print("No next-day picks graded yet.")
        elif cmd == "test-notify":
            notify.test()
        else:
            print(__doc__)
    except Exception as e:
        log(f"ERROR in {cmd}: {e!r}")
        if cmd in ("intraday", "daily") and now_ist().weekday() < 5:
            notify.notify("Market scanner error", f"{cmd}: {str(e)[:180]}", level="signal")
        raise


if __name__ == "__main__":
    main()
