"""Local live server: http://127.0.0.1:8765

Serves the dashboard and /live.json, refreshed in the background:
  - NIFTY 50 / NIFTY BANK and the watched NIFTY option prices from NSE every 30 s
  - prices of stocks currently shown as ideas from Yahoo 1-min bars every 60 s
The 15-min scan (launchd) still produces the ideas; the page reloads when it does.
"""
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from common import DATA, DOCS, log, now_ist, read_json

PORT = 8765
LIVE = {"ts": None, "indices": {}, "nifty_opts": {}, "stocks": {}, "errors": []}
LOCK = threading.Lock()


def market_open():
    n = now_ist()
    return n.weekday() < 5 and "09:10" <= n.strftime("%H:%M") <= "15:35"


def poll_nse():
    from scanner import NSE
    nse, last_ok = None, 0
    while True:
        if not market_open() and LIVE["indices"]:
            time.sleep(60)
            continue
        try:
            if nse is None or time.time() - last_ok > 600:
                nse = NSE()  # refresh cookies now and then
            idx = {}
            for row in nse.get("https://www.nseindia.com/api/allIndices")["data"]:
                if row.get("index") in ("NIFTY 50", "NIFTY BANK"):
                    idx[row["index"]] = {"last": row["last"], "chg": row.get("variation"),
                                         "pchg": row.get("percentChange"), "open": row.get("open"),
                                         "high": row.get("high"), "low": row.get("low")}
            opts, quote_time = {}, None
            scan = read_json(DATA / "state.json", {}).get("last_scan") or {}
            if scan.get("expiry"):
                chain = nse.chain(scan["expiry"])
                quote_time = chain["records"].get("timestamp")
                want = {w["strike"] for w in (scan.get("watch") or {}).values()}
                t = read_json(DATA / "state.json", {}).get("open_trade")
                if t:
                    want.add(t["strike"])
                for r in chain["records"]["data"]:
                    if r["strikePrice"] in want:
                        for sd in ("CE", "PE"):
                            o = r.get(sd)
                            if o:
                                opts[f"{r['strikePrice']}{sd}"] = {"ltp": o.get("lastPrice"), "chg": o.get("change"),
                                                                  "bid": o.get("buyPrice1"), "ask": o.get("sellPrice1")}
            with LOCK:
                LIVE["indices"], LIVE["nifty_opts"] = idx, opts
                LIVE["ts"] = now_ist().isoformat(timespec="seconds")  # when WE fetched
                LIVE["quote_time"] = quote_time  # NSE's own timestamp on the prices
            last_ok = time.time()
        except Exception as e:
            log(f"live: NSE poll failed {e!r}")
            nse = None
        time.sleep(30)


def poll_stocks():
    import yfinance as yf
    while True:
        if not market_open() and LIVE["stocks"]:
            time.sleep(60)
            continue
        try:
            sl = read_json(DATA / "stocks_live.json", {})
            prev = {r["symbol"]: r["prev_close"] for r in sl.get("rows", [])}
            syms = {r["symbol"] for r in sl.get("signals", [])}
            syms |= {p["symbol"] for p in read_json(DATA / "daily.json", {}).get("options", [])}
            syms = sorted(s for s in syms if s not in ("NIFTY", "BANKNIFTY"))
            if syms:
                df = yf.download([s + ".NS" for s in syms], period="1d", interval="1m",
                                 progress=False, auto_adjust=False, threads=True)
                close = df["Close"]
                out = {}
                for s in syms:
                    col = s + ".NS"
                    if col in close and not close[col].dropna().empty:
                        px = float(close[col].dropna().iloc[-1])
                        pc = prev.get(s)
                        out[s] = {"price": round(px, 2), "pchg": round((px / pc - 1) * 100, 2) if pc else None}
                with LOCK:
                    LIVE["stocks"] = out
        except Exception as e:
            log(f"live: stock poll failed {e!r}")
        time.sleep(60)


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/live.json":
            with LOCK:
                body = dict(LIVE)
            body["market_open"] = market_open()
            idx = DOCS / "index.html"
            body["built_epoch"] = idx.stat().st_mtime if idx.exists() else 0
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


def serve():
    threading.Thread(target=poll_nse, daemon=True).start()
    threading.Thread(target=poll_stocks, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(DOCS)))
    log(f"live: serving http://127.0.0.1:{PORT}")
    srv.serve_forever()
