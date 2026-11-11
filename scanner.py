"""NIFTY intraday option scanner (PAPER TRADING), runs every 15 min in market hours.

1. Fetch NIFTY spot + option chain from NSE's public feed.
2. Compute Greeks from NSE's implied volatility.
3. If a paper trade is open: check target / stop-loss / time exit.
4. Otherwise score the market bias; if strong, pick ONE contract (delta ~0.5,
   liquid, tight spread) with +10% target / -5% stop.
5. Notify + log to data/.
"""
import statistics
import time
from datetime import datetime, timedelta

import requests

from common import (CONFIG, DATA, IST, UA, append_csv, bs_price, charges, greeks, log, now_ist,
                    read_csv, read_json, write_json)
from notify import notify

C = CONFIG["intraday"]
STATE_FILE = DATA / "state.json"
SNAP_FILE = DATA / "snapshots.csv"
TRADES_FILE = DATA / "trades.csv"
R, Q = CONFIG["risk_free_rate"], CONFIG["nifty_dividend_yield"]


class NSE:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA, "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/option-chain",
        })
        self._warm()

    def _warm(self):
        self.s.get("https://www.nseindia.com/option-chain", timeout=15)

    def get(self, url):
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=15)
                if r.status_code == 200:
                    return r.json()
                log(f"NSE {r.status_code} for {url}")
            except Exception as e:
                log(f"NSE error {e!r} for {url}")
            time.sleep(2 + attempt * 3)
            self._warm()
        raise RuntimeError(f"NSE fetch failed: {url}")

    def expiries(self):
        return self.get("https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY")["expiryDates"]

    def chain(self, expiry):
        return self.get("https://www.nseindia.com/api/option-chain-v3?type=Indices"
                        f"&symbol=NIFTY&expiry={expiry}")

    def index(self):
        self.all_indices = self.get("https://www.nseindia.com/api/allIndices")["data"]
        for row in self.all_indices:
            if row.get("index") == "NIFTY 50":
                return row
        raise RuntimeError("NIFTY 50 not found in allIndices")


# indices shown on the website (main ones first, then sectors)
MAIN_INDICES = ["NIFTY 50", "NIFTY BANK", "NIFTY FINANCIAL SERVICES", "NIFTY MIDCAP 100", "INDIA VIX"]
SECTOR_INDICES = ["NIFTY PSU BANK", "NIFTY PRIVATE BANK", "NIFTY IT", "NIFTY AUTO", "NIFTY PHARMA", "NIFTY FMCG",
                  "NIFTY METAL", "NIFTY REALTY", "NIFTY ENERGY", "NIFTY MEDIA", "NIFTY OIL & GAS",
                  "NIFTY HEALTHCARE INDEX", "NIFTY CONSUMER DURABLES", "NIFTY INDIA DEFENCE"]


def save_indices(rows):
    want = set(MAIN_INDICES + SECTOR_INDICES)
    out = {}
    for r in rows or []:
        if r.get("index") in want and r.get("last") is not None:
            out[r["index"]] = {"last": r["last"], "chg": r.get("variation"), "pchg": r.get("percentChange"),
                               "open": r.get("open"), "high": r.get("high"), "low": r.get("low"),
                               "prev": r.get("previousClose")}
    if out:
        write_json(DATA / "indices.json", {"time": now_ist().isoformat(timespec="seconds"),
                                          "main": [k for k in MAIN_INDICES if k in out],
                                          "sectors": [k for k in SECTOR_INDICES if k in out], "rows": out})


def expiry_dt(expiry_str):
    return datetime.strptime(expiry_str, "%d-%b-%Y").replace(hour=15, minute=30, tzinfo=IST)


def quote_age_min(nse_ts):
    """Minutes since NSE's own timestamp (e.g. '11-Nov-2026 09:48:25'). None if unparseable."""
    try:
        t = datetime.strptime(nse_ts.strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
        return (now_ist() - t).total_seconds() / 60
    except (ValueError, AttributeError):
        return None


def years_to(expiry_str):
    return max((expiry_dt(expiry_str) - now_ist()).total_seconds(), 60) / (365 * 86400)


def load_state():
    return read_json(STATE_FILE, {"open_trade": None, "day": None, "trades_today": 0,
                                  "losses_today": 0, "last_exit": None, "last_scan": None})


def pick_expiry(expiries):
    today = now_ist().date()
    for e in expiries:
        if (datetime.strptime(e, "%d-%b-%Y").date() - today).days >= C["min_days_to_expiry"]:
            return e
    return expiries[0]


def analyse_chain(chain, expiry):
    rec = chain["records"]
    spot = rec["underlyingValue"]
    rows = [r for r in rec["data"] if r.get("CE") or r.get("PE")]
    strikes = sorted({r["strikePrice"] for r in rows})
    atm = min(strikes, key=lambda k: abs(k - spot))
    band = C["oi_band_strikes"] * C["strike_step"]
    near = [r for r in rows if abs(r["strikePrice"] - atm) <= band]

    def g(r, side, key):
        return (r.get(side) or {}).get(key) or 0

    call_oi = sum(g(r, "CE", "openInterest") for r in near)
    put_oi = sum(g(r, "PE", "openInterest") for r in near)
    above = [r for r in near if r["strikePrice"] > spot]
    below = [r for r in near if r["strikePrice"] < spot]
    atm_row = next(r for r in rows if r["strikePrice"] == atm)
    ivs = [g(atm_row, s, "impliedVolatility") for s in ("CE", "PE") if g(atm_row, s, "impliedVolatility")]

    yrs = years_to(expiry)
    contracts = []
    for r in rows:
        for side in ("CE", "PE"):
            o = r.get(side)
            if not o or not o.get("impliedVolatility"):
                continue
            gk = greeks(spot, r["strikePrice"], yrs, o["impliedVolatility"], side, R, Q)
            if not gk:
                continue
            bid, ask = o.get("buyPrice1") or 0, o.get("sellPrice1") or 0
            contracts.append({
                "side": side, "strike": r["strikePrice"], "ltp": o.get("lastPrice") or 0,
                "bid": bid, "ask": ask, "mid": (bid + ask) / 2 if bid and ask else o.get("lastPrice") or 0,
                "iv": o["impliedVolatility"], "oi": o.get("openInterest") or 0,
                "oi_chg": o.get("changeinOpenInterest") or 0, "volume": o.get("totalTradedVolume") or 0,
                "chg": o.get("change") or 0, **gk,
            })
    return {
        "spot": spot, "timestamp": rec["timestamp"], "atm": atm,
        "atm_iv": sum(ivs) / len(ivs) if ivs else 0,
        "pcr": put_oi / call_oi if call_oi else 0,
        "call_add": sum(g(r, "CE", "changeinOpenInterest") for r in near),
        "put_add": sum(g(r, "PE", "changeinOpenInterest") for r in near),
        "resistance": max(above, key=lambda r: g(r, "CE", "openInterest"))["strikePrice"] if above else None,
        "support": max(below, key=lambda r: g(r, "PE", "openInterest"))["strikePrice"] if below else None,
        "contracts": contracts,
    }


def recent_spot(minutes_ago):
    target = now_ist() - timedelta(minutes=minutes_ago)
    best = None
    for row in read_csv(SNAP_FILE):
        t = datetime.fromisoformat(row["time"])
        gap = abs((t - target).total_seconds())
        if t.date() == target.date() and gap <= 10 * 60 and (best is None or gap < best[0]):
            best = (gap, float(row["spot"]))
    return best[1] if best else None


def iv_median_recent():
    rows = read_csv(SNAP_FILE)[-C["iv_lookback_snapshots"]:]
    vals = [float(r["atm_iv"]) for r in rows if float(r["atm_iv"] or 0) > 0]
    return statistics.median(vals) if len(vals) >= 10 else None


def score_bias(a, idx):
    reasons, score, spot = [], 0, a["spot"]
    day = (spot - idx["open"]) / idx["open"] * 100
    if day > C["trend_pct"]:
        score += 1; reasons.append(f"above day open {day:+.2f}%")
    elif day < -C["trend_pct"]:
        score -= 1; reasons.append(f"below day open {day:+.2f}%")
    else:
        reasons.append(f"flat vs open {day:+.2f}%")

    past = recent_spot(C["momentum_minutes"])
    if past:
        mom = (spot - past) / past * 100
        if mom > C["momentum_pct"]:
            score += 1; reasons.append(f"rising {mom:+.2f}% in {C['momentum_minutes']}m")
        elif mom < -C["momentum_pct"]:
            score -= 1; reasons.append(f"falling {mom:+.2f}% in {C['momentum_minutes']}m")
        else:
            reasons.append(f"momentum flat {mom:+.2f}%")
    else:
        reasons.append("no momentum history yet")

    ca, pa = a["call_add"], a["put_add"]
    # only fresh positions count as a vote; OI falling (positions closing) is not "writers adding"
    adds_p, adds_c = max(pa, 0), max(ca, 0)
    tot = adds_p + adds_c
    oi_bias = (adds_p - adds_c) / tot if tot else 0
    if adds_p > 0 and oi_bias > C["oi_bias_threshold"]:
        score += 1; reasons.append(f"put writers adding {pa:+,} OI vs calls {ca:+,} (support building)")
    elif adds_c > 0 and oi_bias < -C["oi_bias_threshold"]:
        score -= 1; reasons.append(f"call writers adding {ca:+,} OI vs puts {pa:+,} (resistance building)")
    elif tot == 0:
        reasons.append(f"no fresh OI build-up (calls {ca:+,}, puts {pa:+,})")
    else:
        reasons.append(f"OI build-up balanced (calls {ca:+,}, puts {pa:+,})")
    return score, reasons, oi_bias


def choose_contract(a, side):
    cands = []
    for c in a["contracts"]:
        if c["side"] != side or not (C["delta_min"] <= abs(c["delta"]) <= C["delta_max"]):
            continue
        if c["oi"] < C["min_oi"] or not c["bid"] or not c["ask"]:
            continue
        c["spread_pct"] = (c["ask"] - c["bid"]) / c["mid"] * 100
        if c["spread_pct"] <= C["max_spread_pct"]:
            cands.append(c)
    return min(cands, key=lambda c: abs(abs(c["delta"]) - C["delta_target"])) if cands else None


def record_snapshot(a, idx, score, oi_bias, bias, note):
    append_csv(SNAP_FILE, {
        "time": now_ist().isoformat(timespec="seconds"), "nse_time": a["timestamp"],
        "spot": a["spot"], "day_open": idx["open"], "prev_close": idx["previousClose"],
        "atm": a["atm"], "atm_iv": round(a["atm_iv"], 2), "pcr": round(a["pcr"], 3),
        "oi_bias": round(oi_bias, 3), "support": a["support"], "resistance": a["resistance"],
        "score": score, "bias": bias, "note": note,
    })


def save_chain(a, expiry):
    """Strikes around ATM with OI + Greeks for the dashboard's option-chain view."""
    lot, band = C["lot_size"], C["oi_band_strikes"] * C["strike_step"]
    rows = {}
    for c in a["contracts"]:
        if abs(c["strike"] - a["atm"]) <= band:
            rows.setdefault(c["strike"], {"strike": c["strike"]})[c["side"]] = {
                "ltp": c["ltp"], "chg": round(c["chg"], 2), "oi": c["oi"], "oi_chg": c["oi_chg"],
                "volume": c["volume"], "iv": c["iv"], "delta": round(c["delta"], 3),
                "gamma": round(c["gamma"], 5), "theta_lot": round(c["theta"] * lot),
                "vega_lot": round(c["vega"] * lot), "cost_lot": round(c["ltp"] * lot),
            }
    write_json(DATA / "chain.json", {
        "time": now_ist().isoformat(timespec="seconds"), "spot": a["spot"], "expiry": expiry,
        "atm": a["atm"], "pcr": round(a["pcr"], 3), "support": a["support"],
        "resistance": a["resistance"], "lot": lot, "rows": sorted(rows.values(), key=lambda r: r["strike"]),
    })


def _raw_quote(chain, strike, side):
    """Bid/LTP for one contract straight from NSE data (works even when IV is missing)."""
    for r in chain["records"]["data"]:
        if r.get("strikePrice") == strike and r.get(side):
            o = r[side]
            return o.get("buyPrice1") or o.get("lastPrice") or None
    return None


def _intrabar_hit(t, since):
    """Did the option touch stop/target between scans? Estimated from NIFTY 5-min highs/lows
    priced with the trade's entry IV. Returns (reason, price) or (None, None). Stop wins ties."""
    try:
        import yfinance as yf
        df = yf.download("^NSEI", period="1d", interval="5m", progress=False, auto_adjust=False)
        if df.empty:
            return None, None
        df.index = df.index.tz_convert(IST)
        df = df[df.index >= since]
        hi = df["High"].squeeze() if hasattr(df["High"], "squeeze") else df["High"]
        lo = df["Low"].squeeze() if hasattr(df["Low"], "squeeze") else df["Low"]
        for ts in df.index:
            yrs = max((expiry_dt(t["expiry"]) - ts).total_seconds(), 60) / (365 * 86400)
            px = lambda s_: bs_price(float(s_), t["strike"], yrs, t["iv"] / 100, t["side"], R, Q)
            worst, best = (px(lo[ts]), px(hi[ts])) if t["side"] == "CE" else (px(hi[ts]), px(lo[ts]))
            if worst <= t["stop"]:
                return "STOP", t["stop"]
            if best >= t["target"]:
                return "TARGET", t["target"]
    except Exception as e:
        log(f"intrabar check failed {e!r}")
    return None, None


def close_trade(st, price, reason, basis):
    t = st["open_trade"]
    qty = t["lots"] * C["lot_size"]
    gross = (price - t["entry"]) * qty
    cost = charges(t["entry"], price, qty)
    net = gross - cost
    append_csv(TRADES_FILE, {
        "entry_time": t["time"], "exit_time": now_ist().isoformat(timespec="seconds"),
        "contract": f"NIFTY {t['expiry']} {t['strike']} {t['side']}", "side": t["side"],
        "strike": t["strike"], "expiry": t["expiry"], "entry": t["entry"], "exit": round(price, 2),
        "lots": t["lots"], "qty": qty, "result": reason,
        "pct": round((price - t["entry"]) / t["entry"] * 100, 2), "gross_pnl": round(gross, 2),
        "charges": round(cost, 2), "net_pnl": round(net, 2), "entry_delta": t["delta"],
        "entry_iv": t["iv"], "score": t["score"], "mode": CONFIG["mode"], "exit_basis": basis,
    })
    st["open_trade"] = None
    st["last_exit"] = now_ist().isoformat()
    if net < 0 and reason != "MISSED":
        st["losses_today"] = st.get("losses_today", 0) + 1
    return net


def manage_open_trade(nse, st):
    t = st["open_trade"]
    name = f"NIFTY {t['expiry']} {t['strike']} {t['side']}"
    now = now_ist()
    # a trade left over from an earlier day (machine off / missed exit): close it at the last known price
    if t["time"][:10] != now.date().isoformat():
        net = close_trade(st, t.get("last_price", t["entry"]), "MISSED", "last known price (left open overnight)")
        notify(f"⚠️ NIFTY trade closed late: {name}", f"It was still open from {t['time'][:10]}. "
               f"Recorded at last known ₹{t.get('last_price', t['entry']):.2f}, net ₹{net:+,.0f}.", level="signal")
        return
    time_up = now.strftime("%H:%M") >= C["exit_all_by"]
    try:
        chain = nse.chain(t["expiry"])
        age = quote_age_min(chain["records"].get("timestamp", ""))
        bid = _raw_quote(chain, t["strike"], t["side"])
    except Exception as e:  # NSE down: still allow intrabar/time exits below
        log(f"open trade: chain fetch failed {e!r}")
        age, bid = None, None
    stale = age is None or age > C["max_quote_age_min"] or bid is None

    # did it touch the stop/target since the last check?
    since = datetime.fromisoformat(t.get("last_check") or t["time"])
    reason, price = _intrabar_hit(t, since)
    basis = "intrabar estimate (NIFTY 5-min high/low)"
    if not reason and not stale:
        t["last_price"] = bid
        reason = "TARGET" if bid >= t["target"] else "STOP" if bid <= t["stop"] else None
        price, basis = bid, "NSE bid"
    if not reason and time_up:
        price = bid if not stale else t.get("last_price", t["entry"])
        reason, basis = "TIME", "NSE bid" if not stale else "last known price (quote stale/missing)"
    t["last_check"] = now.isoformat(timespec="seconds")
    if not reason:
        if stale:
            log(f"open trade: quote stale/missing (age {age}), holding; will retry")
        else:
            notify("NIFTY: holding paper trade",
                   f"{name} now ₹{bid:.2f} ({(bid - t['entry']) / t['entry'] * 100:+.1f}%). "
                   f"Target ₹{t['target']:.2f} / SL ₹{t['stop']:.2f}")
        return
    net = close_trade(st, price, reason, basis)
    emoji = {"TARGET": "✅", "STOP": "❌", "TIME": "⏱"}[reason]
    notify(f"{emoji} EXIT {reason}: {name}",
           f"Sell at ~₹{price:.2f} (bought ₹{t['entry']:.2f}). Net after charges ₹{net:+,.0f} "
           f"on {t['lots']} lot(s). Basis: {basis}", level="signal")


def scan(nse, st, idx, allow_entry):
    now = now_ist()
    hm = now.strftime("%H:%M")
    expiry = pick_expiry(nse.expiries())
    a = analyse_chain(nse.chain(expiry), expiry)
    score, reasons, oi_bias = score_bias(a, idx)
    age = quote_age_min(a["timestamp"])

    block = None
    if not C.get("open_trades", True):
        block = "info only: NIFTY trades come from the engine (opening-range breakout)"
    elif age is None or age > C["max_quote_age_min"]:
        block = f"NSE data is stale (quote time {a['timestamp']}), no new trades"
    elif not allow_entry:
        block = "holding a trade"
    elif not (C["entry_start"] <= hm <= C["entry_end"]):
        block = f"outside entry window {C['entry_start']}-{C['entry_end']}"
    elif st["trades_today"] >= C["max_trades_per_day"]:
        block = "daily trade limit reached"
    elif st["losses_today"] >= C["max_losses_per_day"]:
        block = f"{st['losses_today']} losses today, stopped for the day"
    elif st["last_exit"] and now - datetime.fromisoformat(st["last_exit"]) < timedelta(minutes=C["cooldown_minutes"]):
        block = "cooling down after last exit"
    med = iv_median_recent()
    if not block and med and a["atm_iv"] > med * C["iv_spike_ratio"]:
        block = f"IV spiked ({a['atm_iv']:.1f} vs usual {med:.1f})"

    side = "CE" if score >= C["min_score"] else "PE" if score <= -C["min_score"] else None
    if side == "CE" and a["resistance"] and (a["resistance"] - a["spot"]) / a["spot"] * 100 < C["min_room_pct"]:
        block = block or f"too close to resistance {a['resistance']}"
    if side == "PE" and a["support"] and (a["spot"] - a["support"]) / a["spot"] * 100 < C["min_room_pct"]:
        block = block or f"too close to support {a['support']}"

    bias = {None: "No clear direction", "CE": "Bullish", "PE": "Bearish"}[side]
    summary = (f"NIFTY {a['spot']:.0f} | {bias} (score {score:+d}) | PCR {a['pcr']:.2f} | "
               f"S {a['support']} / R {a['resistance']} | ATM IV {a['atm_iv']:.1f}")
    log(summary + " | " + "; ".join(reasons))
    note = block or ("signals disagree" if not side else "")

    # the contracts we WOULD buy on each side, shown even when no signal has fired
    watch = {}
    for sd in ("CE", "PE"):
        w = choose_contract(a, sd)
        if w:
            e = w["ask"]
            watch[sd] = {"strike": w["strike"], "ask": e, "delta": round(w["delta"], 2),
                         "theta_lot": round(w["theta"] * C["lot_size"]), "iv": w["iv"],
                         "cost_lot": round(e * C["lot_size"]),
                         "target": round(e * (1 + CONFIG["target_pct"] / 100), 2),
                         "stop": round(e * (1 - CONFIG["stop_pct"] / 100), 2),
                         "profit_lot": round(e * CONFIG["target_pct"] / 100 * C["lot_size"] - charges(e, e * 1.1, C["lot_size"])),
                         "loss_lot": round(-e * CONFIG["stop_pct"] / 100 * C["lot_size"] - charges(e, e * 0.95, C["lot_size"]))}
    c = choose_contract(a, side) if side and not block else None
    if side and not block and not c:
        note = f"no liquid contract with delta {C['delta_min']}-{C['delta_max']}"
    if c and c["ask"] * C["lot_size"] > CONFIG["capital_per_trade"]:
        note = f"1 lot costs ₹{c['ask'] * C['lot_size']:,.0f}, above budget"
        c = None
    record_snapshot(a, idx, score, oi_bias, bias, note or "signal")
    save_chain(a, expiry)
    st["last_scan"] = {"time": now.isoformat(timespec="seconds"), "spot": a["spot"], "bias": bias,
                       "score": score, "pcr": round(a["pcr"], 3), "support": a["support"],
                       "resistance": a["resistance"], "atm_iv": round(a["atm_iv"], 2),
                       "reasons": reasons, "note": note or "signal", "expiry": expiry,
                       "watch": watch, "min_score": C["min_score"]}
    if not c:
        if allow_entry and C.get("open_trades", True):
            notify("NIFTY: no trade", f"{summary}. {note}.")
        return

    entry = c["ask"]
    lot = C["lot_size"]
    lots = max(1, int(CONFIG["capital_per_trade"] // (entry * lot)))
    target = round(entry * (1 + CONFIG["target_pct"] / 100), 2)
    stop = round(entry * (1 - CONFIG["stop_pct"] / 100), 2)
    st["open_trade"] = {
        "time": now.isoformat(timespec="seconds"), "expiry": expiry, "side": side,
        "strike": c["strike"], "entry": entry, "target": target, "stop": stop, "lots": lots,
        "delta": round(c["delta"], 3), "theta_lot": round(c["theta"] * lot, 1), "iv": c["iv"],
        "score": score, "last_price": entry,
    }
    st["trades_today"] += 1
    notify(f"{'📈' if side == 'CE' else '📉'} BUY NIFTY {expiry} {c['strike']} {side} [{CONFIG['mode'].upper()}]",
           f"Buy ≤ ₹{entry:.2f} × {lots} lot ({lots * lot} qty, ₹{entry * lots * lot:,.0f}). "
           f"Target ₹{target:.2f} (+{CONFIG['target_pct']}%), SL ₹{stop:.2f} (-{CONFIG['stop_pct']}%), "
           f"exit by {C['exit_all_by']}. Δ {c['delta']:+.2f}, θ ₹{c['theta'] * lot:.0f}/lot/day, IV {c['iv']:.1f}. "
           f"Why: {'; '.join(reasons)}", level="signal")


def market_open(now):
    return now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:30"


def run(force=False):
    now = now_ist()
    if not force and not market_open(now):
        log("intraday: market closed, skipping")
        return False
    st = load_state()
    today = now.date().isoformat()
    if st.get("day") != today:
        st.update(day=today, trades_today=0, losses_today=0, last_exit=None)

    nse = NSE()
    idx = nse.index()
    try:
        save_indices(nse.all_indices)
    except Exception as e:
        log(f"intraday: indices not saved {e!r}")
    ts = (idx.get("timeVal") or "").strip()
    try:  # holiday check; NSE sometimes leaves this field blank, then we just carry on
        if ts and not force and datetime.strptime(ts.split()[0], "%d-%b-%Y").date() != now.date():
            log(f"intraday: market holiday (NSE time {ts})")
            return False
    except (ValueError, IndexError):
        pass

    if st.get("open_trade"):
        manage_open_trade(nse, st)
    scan(nse, st, idx, allow_entry=not st.get("open_trade"))
    write_json(STATE_FILE, st)
    return True


def report():
    rows = read_csv(TRADES_FILE)
    if not rows:
        print("No closed NIFTY paper trades yet.")
        return
    nets = [float(r["net_pnl"]) for r in rows]
    wins = [n for n in nets if n > 0]
    print(f"NIFTY intraday: {len(rows)} trades, win rate {len(wins) / len(rows) * 100:.0f}%, "
          f"net P&L ₹{sum(nets):,.0f} after charges")
    for r in rows[-15:]:
        print(f"  {r['entry_time'][:16]}  {r['contract']:<30} {r['result']:<6} "
              f"{float(r['pct']):+6.1f}%  ₹{float(r['net_pnl']):+,.0f}")
