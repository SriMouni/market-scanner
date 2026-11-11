"""Live F&O stock scanner - runs with the 15-min intraday job.

Prices: Yahoo Finance 5-minute bars (near-live, works from any server).
Each signal gives TWO ways to trade it:
  F&O    - buy a CE/PE option. Premium is a Black-Scholes ESTIMATE (NSE daily IV
           at the live price), so confirm the real price in Groww.
  Normal - buy shares intraday (or short-sell for a down move) with a stock-price
           target/stop. Uses real prices, so its track record is exact.

Signal (long; short is the mirror):
  up >= 1% on the day, above VWAP, up >= 0.2% in last 30 min,
  volume >= 1.5x normal for this time of day, above the 15-min opening range,
  within 0.5% of the day's high. Bonus if last night's scan had the same view.
At most `max_per_sector` signals per sector so one hot sector can't fill the list.
"""
import csv
from datetime import datetime

import pandas as pd

from common import (CONFIG, DATA, IST, append_csv, bs_price, charges, greeks, implied_vol, log,
                    now_ist, read_json, write_json)
from notify import notify

S = CONFIG["stocks"]
R = CONFIG["risk_free_rate"]
OUT = DATA / "stocks_live.json"
STATE = DATA / "stock_state.json"
TRADES = DATA / "stock_trades.csv"
CASH_TRADES = DATA / "cash_trades.csv"
BHAV_DIR = DATA / "bhav"
SECTOR_FILE = DATA / "ind_nifty500list.csv"
YAHOO_FIX = {"M&M": "M&M.NS", "BAJAJ-AUTO": "BAJAJ-AUTO.NS"}


# ------------------------------------------------------------------ inputs
def latest_bhav():
    files = sorted(BHAV_DIR.glob("fo_*.csv.gz"))
    if not files:
        import daily
        daily.latest_fo()
        files = sorted(BHAV_DIR.glob("fo_*.csv.gz"))
    f = files[-1]
    return datetime.strptime(f.name[3:11], "%Y%m%d").date(), pd.read_csv(f)


def load_sectors():
    """Symbol -> (sector, company name) from NSE's NIFTY 500 list (refreshed weekly)."""
    if not SECTOR_FILE.exists() or (datetime.now().timestamp() - SECTOR_FILE.stat().st_mtime) > 7 * 86400:
        try:
            import daily
            r = daily.http.get("https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv", timeout=30)
            if r.ok and "Symbol" in r.text:
                SECTOR_FILE.write_text(r.text)
        except Exception as e:
            log(f"stocks: sector list refresh failed {e!r}")
    out = {}
    if SECTOR_FILE.exists():
        with SECTOR_FILE.open() as f:
            for row in csv.DictReader(f):
                sec = row["Industry"]
                if sec == "Financial Services" and " Bank" in row["Company Name"]:
                    sec = "Banks"  # NSE lumps banks with NBFCs/insurers
                out[row["Symbol"]] = (sec, row["Company Name"])
    return out


def universe(fo):
    fut = fo[fo["FinInstrmTp"] == "STF"].sort_values("XpryDt").groupby("TckrSymb", as_index=False).first()
    return fut.sort_values("TtlTrfVal", ascending=False).head(S["universe_top_n"])["TckrSymb"].tolist()


def fetch_bars(symbols):
    import yfinance as yf
    tick = {s: YAHOO_FIX.get(s, s + ".NS") for s in symbols}
    df = yf.download(list(tick.values()), period="5d", interval="5m", progress=False,
                     auto_adjust=False, threads=True)
    df.index = df.index.tz_convert(IST)
    return tick, df


# ----------------------------------------------------------------- metrics
def metrics(sym, t, df, today):
    try:
        c, v = df["Close"][t].dropna(), df["Volume"][t].fillna(0)
        h, l = df["High"][t], df["Low"][t]
    except KeyError:
        return None
    if c.empty:
        return None
    dates = c.index.date
    if today not in set(dates):
        return None
    td, prev = c[dates == today], c[dates < today]
    if len(td) < 3 or prev.empty:
        return None
    age = (datetime.now(IST) - td.index[-1].to_pydatetime()).total_seconds() / 60
    if age > S["max_bar_age_min"] + 5:  # +5: a bar is stamped at its start
        return None  # stale quote: don't use it for signals
    vt, ht, lt = v[td.index], h[td.index], l[td.index]
    tp = (ht + lt + td) / 3
    vwap = float((tp * vt).sum() / vt.sum()) if vt.sum() > 0 else float(td.iloc[-1])
    price, prev_close = float(td.iloc[-1]), float(prev.iloc[-1])
    n = len(td)
    past = []
    for d in sorted(set(dates[dates < today]))[-4:]:
        dv = v[c.index[dates == d]]
        if len(dv) >= n:
            past.append(float(dv.iloc[:n].sum()))
    rvol = float(vt.sum()) / (sum(past) / len(past)) if past and sum(past) > 0 else None
    back = td.iloc[-7] if n >= 7 else td.iloc[0]
    day_h, day_l = float(ht.max()), float(lt.min())
    return {
        "symbol": sym, "price": round(price, 2), "prev_close": round(prev_close, 2),
        "chg": round((price / prev_close - 1) * 100, 2), "vwap": round(vwap, 2),
        "vs_vwap": round((price / vwap - 1) * 100, 2), "mom30": round((price / float(back) - 1) * 100, 2),
        "rvol": round(rvol, 2) if rvol else None, "day_high": round(day_h, 2), "day_low": round(day_l, 2),
        "orb_high": round(float(ht.iloc[:3].max()), 2), "orb_low": round(float(lt.iloc[:3].min()), 2),
        "from_high": round((price / day_h - 1) * 100, 2), "from_low": round((price / day_l - 1) * 100, 2),
        "bar_time": td.index[-1].strftime("%H:%M"),
    }


def classify(m, daily_view):
    up = (m["chg"] >= S["chg_min"] and m["vs_vwap"] > 0 and m["mom30"] >= S["mom_min"]
          and (m["rvol"] or 0) >= S["rvol_min"] and m["price"] >= m["orb_high"] and m["from_high"] >= -S["near_extreme_pct"])
    dn = (m["chg"] <= -S["chg_min"] and m["vs_vwap"] < 0 and m["mom30"] <= -S["mom_min"]
          and (m["rvol"] or 0) >= S["rvol_min"] and m["price"] <= m["orb_low"] and m["from_low"] <= S["near_extreme_pct"])
    side = "CE" if up else "PE" if dn else None
    checks = {
        "move": abs(m["chg"]) >= S["chg_min"],
        "vwap": (m["vs_vwap"] > 0) if m["chg"] >= 0 else (m["vs_vwap"] < 0),
        "momentum": abs(m["mom30"]) >= S["mom_min"] and (m["mom30"] > 0) == (m["chg"] >= 0),
        "volume": (m["rvol"] or 0) >= S["rvol_min"],
        "range": (m["price"] >= m["orb_high"]) if m["chg"] >= 0 else (m["price"] <= m["orb_low"]),
    }
    score = abs(m["chg"]) + min(m["rvol"] or 0, 5) * 0.5 + abs(m["mom30"]) * 2
    agree = bool(side) and daily_view.get(m["symbol"]) == side
    return side, round(score + (1 if agree else 0), 2), checks, agree


# --------------------------------------------------------- the two trade types
def option_for(fo, bhav_day, sym, side, spot):
    opts = fo[(fo["TckrSymb"] == sym) & (fo["OptnTp"] == side) & (fo["FinInstrmTp"] == "STO")]
    today = now_ist().date()
    exps = sorted(e for e in opts["XpryDt"].unique()
                  if (datetime.strptime(e, "%Y-%m-%d").date() - today).days >= S["min_days_to_expiry"])
    if not exps:
        return None
    exp = exps[0]
    exp_dt = datetime.strptime(exp, "%Y-%m-%d").replace(hour=15, minute=30, tzinfo=IST)
    yrs_then = (exp_dt.date() - bhav_day).days / 365
    yrs_now = max((exp_dt - now_ist()).total_seconds(), 3600) / (365 * 86400)
    best = None
    for _, o in opts[opts["XpryDt"] == exp].iterrows():
        if o["TtlTradgVol"] < CONFIG["daily"]["min_contracts_traded"] or o["ClsPric"] <= 0:
            continue
        k = float(o["StrkPric"])
        if abs(k / spot - 1) > 0.08:
            continue
        iv = implied_vol(float(o["ClsPric"]), float(o["UndrlygPric"]), k, yrs_then, side, R)
        if not iv:
            continue
        g = greeks(spot, k, yrs_now, iv, side, R)
        if not (CONFIG["intraday"]["delta_min"] <= abs(g["delta"]) <= CONFIG["intraday"]["delta_max"]):
            continue
        if best is None or abs(abs(g["delta"]) - 0.5) < abs(abs(best["delta"]) - 0.5):
            lot = int(o["NewBrdLotQty"])
            e = round(bs_price(spot, k, yrs_now, iv / 100, side, R), 2)
            tgt, sl = round(e * (1 + CONFIG["target_pct"] / 100), 2), round(e * (1 - CONFIG["stop_pct"] / 100), 2)
            best = {"expiry": exp, "strike": k, "est": e, "iv": round(iv, 1), "delta": round(g["delta"], 2),
                    "theta_lot": round(g["theta"] * lot), "lot": lot, "cost_lot": round(e * lot),
                    "target": tgt, "stop": sl,
                    "profit_lot": round((tgt - e) * lot - charges(e, tgt, lot)),
                    "loss_lot": round((sl - e) * lot - charges(e, sl, lot))}
    return best


def cash_charges(buy, sell, qty):
    """Estimated intraday equity charges for one round trip (₹)."""
    ch = CONFIG["cash_charges"]
    bv, sv = buy * qty, sell * qty
    brokerage = min(ch["brokerage_per_order"], bv * ch["brokerage_pct"] / 100) + \
        min(ch["brokerage_per_order"], sv * ch["brokerage_pct"] / 100)
    stt = sv * ch["stt_sell_pct"] / 100
    exch = (bv + sv) * ch["exchange_pct"] / 100
    sebi = (bv + sv) * 10 / 1e7
    stamp = bv * ch["stamp_buy_pct"] / 100
    return brokerage + stt + exch + sebi + stamp + (brokerage + exch + sebi) * 0.18


def cash_for(price, side):
    """Normal (share) trade: buy for an up move, short-sell intraday for a down move."""
    qty = int(CONFIG["capital_per_trade"] // price)
    if qty < 1:
        return None
    t, s = S["cash_target_pct"] / 100, S["cash_stop_pct"] / 100
    long = side == "CE"
    tgt = round(price * (1 + t if long else 1 - t), 2)
    sl = round(price * (1 - s if long else 1 + s), 2)
    gain = abs(tgt - price) * qty - cash_charges(price, tgt, qty)
    loss = -abs(price - sl) * qty - cash_charges(price, sl, qty)
    return {"action": "BUY" if long else "SELL (short)", "qty": qty, "entry": price,
            "invest": round(qty * price), "target": tgt, "stop": sl,
            "profit": round(gain), "loss": round(loss)}


def diversify(signals, cap):
    """Keep the best signals with at most `cap` per sector."""
    seen, out = {}, []
    for r in signals:
        if seen.get(r["sector"], 0) < cap:
            out.append(r)
            seen[r["sector"]] = seen.get(r["sector"], 0) + 1
    return out


# ------------------------------------------------------------------ paper trades
def est_price(fo, t, spot):
    exp_dt = datetime.strptime(t["expiry"], "%Y-%m-%d").replace(hour=15, minute=30, tzinfo=IST)
    yrs = max((exp_dt - now_ist()).total_seconds(), 3600) / (365 * 86400)
    return round(bs_price(spot, t["strike"], yrs, t["iv"] / 100, t["side"], R), 2)


def manage_options(st, fo, by_sym, hm, now, df=None, tick=None):
    """Option exits are a MODEL: Black-Scholes at the stock's 5-min highs/lows with the entry IV,
    minus slippage. Stop is checked before target within each bar."""
    slip = S["model_slippage_pct"] / 100
    still = []
    for t in st["open"]:
        m = by_sym.get(t["symbol"])
        reason = px = None
        if df is not None and tick and tick.get(t["symbol"]):
            try:
                tk = tick[t["symbol"]]
                bars = df.loc[df.index > datetime.fromisoformat(t.get("last_check") or t["time"])]
                for ts in bars["High"][tk].dropna().index:
                    h, l = float(bars["High"][tk][ts]), float(bars["Low"][tk][ts])
                    worst = est_price(fo, t, l if t["side"] == "CE" else h) * (1 - slip)
                    best = est_price(fo, t, h if t["side"] == "CE" else l) * (1 - slip)
                    if worst <= t["stop"]:
                        reason, px = "STOP", t["stop"]
                        break
                    if best >= t["target"]:
                        reason, px = "TARGET", t["target"]
                        break
            except (KeyError, ValueError):
                pass
        t["last_check"] = now.isoformat(timespec="seconds")
        if m:
            t["last_est"], t["last_spot"] = round(est_price(fo, t, m["price"]) * (1 - slip), 2), m["price"]
        if not reason and hm >= CONFIG["intraday"]["exit_all_by"]:
            reason, px = "TIME", t.get("last_est", t["entry"])
        if not reason:
            still.append(t)
            continue
        net = (px - t["entry"]) * t["lot"] - charges(t["entry"], px, t["lot"])
        append_csv(TRADES, {"entry_time": t["time"], "exit_time": now.isoformat(timespec="seconds"),
                            "contract": t["contract"], "side": t["side"], "spot_in": t["spot"],
                            "spot_out": (m or {}).get("price", t.get("last_spot")), "entry_est": t["entry"], "exit_est": px, "lot": t["lot"],
                            "result": reason, "pct": round((px / t["entry"] - 1) * 100, 2), "net_pnl": round(net, 2),
                            "basis": "model estimate (no live option quotes)"})
        notify(f"{'✅' if reason == 'TARGET' else '❌' if reason == 'STOP' else '⏱'} F&O EXIT {reason}: {t['contract']}",
               f"{t['symbol']} now ₹{(m or {}).get('price', t.get('last_spot', 0)):,.2f}. Option est. ₹{px:.2f} (bought ~₹{t['entry']:.2f}). "
               f"Est. net ₹{net:+,.0f} per lot. Check the real price in Groww.", level="signal")
    st["open"] = still


def manage_cash(st, df, tick, hm, now):
    """Exact exits from 5-min bars: if a bar touched both target and stop, assume the stop."""
    still = []
    for t in st["cash_open"]:
        tk = tick.get(t["symbol"])
        try:
            bars = df.loc[df.index > datetime.fromisoformat(t["time"])]
            hi, lo, cl = bars["High"][tk].dropna(), bars["Low"][tk].dropna(), bars["Close"][tk].dropna()
        except KeyError:
            still.append(t)
            continue
        long = t["action"] == "BUY"
        reason = exit_px = None
        for ts in hi.index:
            h, l = float(hi[ts]), float(lo[ts])
            hit_stop = (l <= t["stop"]) if long else (h >= t["stop"])
            hit_tgt = (h >= t["target"]) if long else (l <= t["target"])
            if hit_stop:
                reason, exit_px = "STOP", t["stop"]
                break
            if hit_tgt:
                reason, exit_px = "TARGET", t["target"]
                break
        last = float(cl.iloc[-1]) if not cl.empty else t["entry"]
        if not reason and hm >= CONFIG["intraday"]["exit_all_by"]:
            reason, exit_px = "TIME", last
        t["last"] = round(last, 2)
        if not reason:
            still.append(t)
            continue
        gross = (exit_px - t["entry"]) * t["qty"] * (1 if long else -1)
        net = gross - cash_charges(t["entry"], exit_px, t["qty"])
        append_csv(CASH_TRADES, {"entry_time": t["time"], "exit_time": now.isoformat(timespec="seconds"),
                                 "symbol": t["symbol"], "action": t["action"], "qty": t["qty"],
                                 "entry": t["entry"], "exit": round(exit_px, 2), "result": reason,
                                 "pct": round((exit_px / t["entry"] - 1) * 100 * (1 if long else -1), 2),
                                 "net_pnl": round(net, 2)})
        notify(f"{'✅' if reason == 'TARGET' else '❌' if reason == 'STOP' else '⏱'} SHARES EXIT {reason}: {t['symbol']}",
               f"{'Sell' if long else 'Buy back'} {t['qty']} at ~₹{exit_px:,.2f} (entry ₹{t['entry']:,.2f}). "
               f"Net after charges ₹{net:+,.0f}.", level="signal")
    st["cash_open"] = still


# --------------------------------------------------------------------- run
def run():
    now = now_ist()
    hm, today = now.strftime("%H:%M"), now.date()
    bhav_day, fo = latest_bhav()
    sectors = load_sectors()
    syms = universe(fo)
    tick, df = fetch_bars(syms)
    daily_view = {p["symbol"]: p["side"] for p in read_json(DATA / "daily.json", {}).get("options", [])}

    rows = []
    for s in syms:
        m = metrics(s, tick[s], df, today)
        if not m:
            continue
        m["sector"], m["name"] = sectors.get(s, ("Other", s))
        m["signal"], m["score"], m["checks"], m["agree"] = classify(m, daily_view)
        rows.append(m)
    if not rows:
        log("stocks: no live data for today (holiday or Yahoo issue)")
        return False
    by_sym = {r["symbol"]: r for r in rows}

    st = read_json(STATE, {})
    if st.get("day") != today.isoformat():
        for t in st.get("open", []):  # never silently drop a position
            px = t.get("last_est", t["entry"])
            net = (px - t["entry"]) * t["lot"] - charges(t["entry"], px, t["lot"])
            append_csv(TRADES, {"entry_time": t["time"], "exit_time": now.isoformat(timespec="seconds"),
                                "contract": t["contract"], "side": t["side"], "spot_in": t["spot"],
                                "spot_out": t.get("last_spot"), "entry_est": t["entry"], "exit_est": px,
                                "lot": t["lot"], "result": "MISSED", "pct": round((px / t["entry"] - 1) * 100, 2),
                                "net_pnl": round(net, 2), "basis": "last known estimate (left open overnight)"})
        for t in st.get("cash_open", []):
            px = t.get("last", t["entry"])
            long = t["action"] == "BUY"
            net = (px - t["entry"]) * t["qty"] * (1 if long else -1) - cash_charges(t["entry"], px, t["qty"])
            append_csv(CASH_TRADES, {"entry_time": t["time"], "exit_time": now.isoformat(timespec="seconds"),
                                     "symbol": t["symbol"], "action": t["action"], "qty": t["qty"],
                                     "entry": t["entry"], "exit": round(px, 2), "result": "MISSED",
                                     "pct": round((px / t["entry"] - 1) * 100 * (1 if long else -1), 2),
                                     "net_pnl": round(net, 2)})
        if st.get("open") or st.get("cash_open"):
            log(f"stocks: recorded {len(st.get('open', []))} option + {len(st.get('cash_open', []))} share trades left open overnight as MISSED")
        st = {"day": today.isoformat(), "open": [], "taken": []}
    st.setdefault("cash_open", [])
    st.setdefault("cash_taken", [])
    manage_options(st, fo, by_sym, hm, now, df, tick)
    manage_cash(st, df, tick, hm, now)

    from analysis import chart_check
    raw = []
    for r in (x for x in rows if x["signal"]):
        try:
            bars = df.xs(tick[r["symbol"]], axis=1, level=1)[["Open", "High", "Low", "Close", "Volume"]]
            r["chart"] = chart_check(bars, r["signal"], "intraday")
        except KeyError:
            r["chart"] = None
        if r["chart"] and r["chart"]["verdict"] == "against":
            continue  # e.g. a reversal candle against the move: skip
        if r["chart"]:
            r["score"] = round(r["score"] + (r["chart"]["passed"] - 3) * 0.5, 2)
        raw.append(r)
    raw.sort(key=lambda r: -r["score"])
    for r in raw:
        o = option_for(fo, bhav_day, r["symbol"], r["signal"], r["price"])
        r["option"] = o
        if o:
            exp_label = datetime.strptime(o["expiry"], "%Y-%m-%d").strftime("%d %b")
            r["contract"] = f"{r['symbol']} {exp_label} {o['strike']:g} {r['signal']}"
            r["affordable"] = o["cost_lot"] <= CONFIG["capital_per_trade"]
        r["cash"] = cash_for(r["price"], r["signal"])
    signals = diversify(raw, S["max_per_sector"])
    hot = {}
    for r in raw:
        hot[r["sector"]] = hot.get(r["sector"], 0) + 1

    can_enter = S["entry_start"] <= hm <= S["entry_end"]
    for r in signals:
        if not can_enter or r["symbol"] in st["taken"] or len(st["taken"]) >= S["max_trades_per_day"]:
            continue
        msg = []
        o, c = r.get("option"), r.get("cash")
        if o and r.get("affordable") and len(st["open"]) < S["max_open"]:
            st["open"].append({"time": now.isoformat(timespec="seconds"), "symbol": r["symbol"], "side": r["signal"],
                               "contract": r["contract"], "expiry": o["expiry"], "strike": o["strike"], "iv": o["iv"],
                               "lot": o["lot"], "spot": r["price"], "entry": round(o["est"] * (1 + S["model_slippage_pct"] / 100), 2),
                               "last_est": o["est"],
                               "last_spot": r["price"], "target": o["target"], "stop": o["stop"]})
            msg.append(f"F&O: buy 1 lot {r['contract']} at ~₹{o['est']:.2f} (est.) = ₹{o['cost_lot']:,}. "
                       f"Target ₹{o['target']:.2f}, stop ₹{o['stop']:.2f}.")
        if c:
            st["cash_open"].append({"time": now.isoformat(timespec="seconds"), "symbol": r["symbol"], **c})
            msg.append(f"Shares: {c['action']} {c['qty']} {r['symbol']} at ~₹{c['entry']:,.2f} (₹{c['invest']:,}). "
                       f"Target ₹{c['target']:,.2f} (+₹{c['profit']:,}), stop ₹{c['stop']:,.2f} (₹{c['loss']:,}).")
        if not msg:
            continue
        st["taken"].append(r["symbol"])
        why = (f"{r['symbol']} ({r['sector']}) {r['chg']:+.2f}% today, volume {r['rvol']:.1f}x normal, "
               f"still {'rising' if r['signal'] == 'CE' else 'falling'} in the last 30 min"
               + (", agrees with last night's scan" if r["agree"] else ""))
        notify(f"{'📈' if r['signal'] == 'CE' else '📉'} {r['symbol']} {'UP' if r['signal'] == 'CE' else 'DOWN'} signal [{CONFIG['mode'].upper()}]",
               "\n".join(msg) + f"\nWhy: {why}. Exit by {CONFIG['intraday']['exit_all_by']}.", level="signal")

    # strong movers we did not practice-trade (daily limits used up): still tell the user, once per stock
    st.setdefault("alerted", [])
    room = S.get("max_alerts_per_day", 6) - len(st["alerted"])
    fresh = [r for r in signals if can_enter and r["symbol"] not in st["taken"] and r["symbol"] not in st["alerted"]
             and r.get("chart") and r["chart"]["verdict"] in ("strong", "ok")][:max(room, 0)]
    if fresh:
        import alerts
        st["alerted"] += [r["symbol"] for r in fresh]
        notify(*alerts.stock_watch(fresh), level="signal")

    rows.sort(key=lambda r: -abs(r["chg"]))
    write_json(OUT, {"time": now.isoformat(timespec="seconds"), "bar_time": max(r["bar_time"] for r in rows),
                     "bhav_date": bhav_day.isoformat(), "scanned": len(rows), "rows": rows,
                     "signals": signals, "all_signals": len(raw), "hot_sectors": hot,
                     "entry_open": can_enter})
    write_json(STATE, st)
    log(f"stocks: scanned {len(rows)}, {len(raw)} signals ({len(signals)} after sector cap), "
        f"{len(st['open'])} F&O + {len(st['cash_open'])} share trades open")
    return True
