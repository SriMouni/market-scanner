"""NIFTY paper-trading engine: reliable quotes, independent exits, realistic fills, auditable ledger.

Run `python app.py monitor` during market hours. It loops every `poll_sec` seconds:
  * EXIT WATCH (every poll): open position checked against a validated NSE bid.
  * FILLS (every poll): a pending buy fills only if the validated ask is <= the limit;
    otherwise it is recorded as UNFILLED after `fill_timeout_sec`.
  * SIGNAL (each new 5-min bar): ONE baseline setup, an opening-range breakout on NIFTY.
  * RECORDER (every poll): ATM +-N strikes bid/ask saved to data/quotes/ for later replay.

Everything that happens is appended to data/ledger.jsonl (append-only). State is written
atomically to data/engine_state.json so a crash/restart never loses a position.

Outcome the strategy is judged on:
  "After the signal, does the executable exit BID reach +target% on the entry ASK before
   -stop%, by the time exit?"  Outcomes: TARGET, STOP, TIME, UNFILLED, MISSED.
"""
import csv
import fcntl
import gzip
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from common import CONFIG, DATA, IST, charges, greeks, log, now_ist, read_json
from notify import notify

E = CONFIG["engine"]
LOT = CONFIG["intraday"]["lot_size"]
STEP = CONFIG["intraday"]["strike_step"]
R, Q = CONFIG["risk_free_rate"], CONFIG["nifty_dividend_yield"]
STATE = DATA / "engine_state.json"
LEDGER = DATA / "ledger.jsonl"
TRADES = DATA / "engine_trades.csv"
LOCK = DATA / "engine.lock"
QUOTES_DIR = DATA / "quotes"
VERIFIED = ("TARGET", "STOP", "TIME")  # exits priced from a validated NSE bid
TRADE_FIELDS = ["trade_id", "signal_time", "fill_time", "exit_time", "side", "strike", "expiry", "days_to_expiry",
                "signal_ask", "entry", "exit", "target", "stop", "result", "exit_basis", "gross_pnl", "charges",
                "net_pnl", "pct", "slippage", "mfe_pct", "mae_pct", "entry_delta", "entry_theta_lot", "entry_iv",
                "spot_at_signal", "or_high", "or_low", "hour", "rule"]


# ----------------------------------------------------------------- durability
@contextmanager
def locked():
    LOCK.touch(exist_ok=True)
    with LOCK.open("r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def load():
    return read_json(STATE, {"day": None, "position": None, "pending": None, "trades_today": 0,
                             "losses_today": 0, "breakouts": [], "last_bar": None, "rejects_today": 0})


def save(st):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, default=str))
    os.replace(tmp, STATE)  # atomic


def event(kind, **kw):
    rec = {"ts": now_ist().isoformat(timespec="seconds"), "event": kind, **kw}
    with LEDGER.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def trade_ids():
    if not TRADES.exists():
        return set()
    with TRADES.open() as f:
        return {r["trade_id"] for r in csv.DictReader(f)}


def ledger_has(kind, trade_id):
    if not LEDGER.exists():
        return False
    needle = f'"trade_id": "{trade_id}"'
    with LEDGER.open() as f:
        return any(needle in l and f'"event": "{kind}"' in l for l in f)


def write_trade(row):
    """Append a result row once per trade_id (idempotent: safe to repeat after a crash)."""
    if row["trade_id"] in trade_ids():
        return False
    new = not TRADES.exists()
    with TRADES.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
    return True


def rewrite_trades(rows):
    tmp = TRADES.with_suffix(".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, TRADES)


# --------------------------------------------------------------------- quotes
def nse_age_min(stamp):
    try:
        t = datetime.strptime(stamp.strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
        return (now_ist() - t).total_seconds() / 60
    except (ValueError, AttributeError):
        return None


def quote(chain, strike, side):
    """Contract quote + NSE timestamp from a chain response (no dependence on IV)."""
    rec = chain["records"]
    for r in rec["data"]:
        if r.get("strikePrice") == strike and r.get(side):
            o = r[side]
            return {"bid": o.get("buyPrice1") or 0, "ask": o.get("sellPrice1") or 0, "ltp": o.get("lastPrice") or 0,
                    "iv": o.get("impliedVolatility") or 0, "oi": o.get("openInterest") or 0,
                    "vol": o.get("totalTradedVolume") or 0, "nse_ts": rec.get("timestamp", ""),
                    "spot": rec.get("underlyingValue")}
    return None


def validate(q, max_age_min):
    """Reject stale, empty, crossed or too-wide quotes. Returns reason or None if OK."""
    if not q:
        return "contract missing"
    age = nse_age_min(q["nse_ts"])
    if age is None:
        return "no NSE timestamp"
    if age > max_age_min:
        return f"stale ({age:.1f} min old)"
    if q["bid"] <= 0 or q["ask"] <= 0:
        return "no bid/ask"
    if q["ask"] < q["bid"]:
        return "crossed (ask < bid)"
    if (q["ask"] - q["bid"]) / ((q["ask"] + q["bid"]) / 2) * 100 > E["max_spread_pct"]:
        return f"spread too wide ({q['bid']}/{q['ask']})"
    return None


def record_quotes(chain):
    """Save ATM +- N strikes every poll, building our own history for replay."""
    rec = chain["records"]
    spot = rec.get("underlyingValue")
    if not spot:
        return
    atm = round(spot / STEP) * STEP
    QUOTES_DIR.mkdir(exist_ok=True)
    f = QUOTES_DIR / f"{now_ist():%Y-%m-%d}.csv.gz"
    new = not f.exists()
    with gzip.open(f, "at", newline="") as g:
        w = csv.writer(g)
        if new:
            w.writerow(["poll_ts", "nse_ts", "spot", "expiry", "strike", "side", "bid", "ask", "ltp", "iv", "oi", "vol"])
        for r in rec["data"]:
            k = r.get("strikePrice")
            if k is None or abs(k - atm) > E["record_strikes"] * STEP:
                continue
            for sd in ("CE", "PE"):
                o = r.get(sd)
                if o:
                    w.writerow([now_ist().isoformat(timespec="seconds"), rec.get("timestamp"), spot,
                                o.get("expiryDate"), k, sd, o.get("buyPrice1"), o.get("sellPrice1"),
                                o.get("lastPrice"), o.get("impliedVolatility"), o.get("openInterest"),
                                o.get("totalTradedVolume")])


# ------------------------------------------------------------------- strategy
def nifty_bars():
    """Today's NIFTY 5-min bars (Yahoo). Drops the bar still forming."""
    import yfinance as yf
    df = yf.download("^NSEI", period="1d", interval="5m", progress=False, auto_adjust=False)
    if df.empty:
        return None
    df.index = df.index.tz_convert(IST)
    df = df[df.index.date == now_ist().date()]
    cols = {c: df[c].squeeze() if hasattr(df[c], "squeeze") else df[c] for c in ("Open", "High", "Low", "Close")}
    import pandas as pd
    df = pd.DataFrame(cols)
    done = df[df.index + timedelta(minutes=5) <= now_ist()]
    return done


def orb_signal(bars, st):
    """Opening-range breakout: first `or_minutes` define the range; a 5-min CLOSE beyond it is the signal.
    Each direction can trigger once per day. Returns (side, info) or (None, reason)."""
    if bars is None or bars.empty:
        return None, "no NIFTY bars yet"
    n_or = E["or_minutes"] // 5
    if len(bars) < n_or + 1:
        return None, f"building opening range ({len(bars)}/{n_or} bars)"
    orng = bars.iloc[:n_or]
    hi, lo = float(orng["High"].max()), float(orng["Low"].min())
    last = bars.iloc[-1]
    last_end = bars.index[-1] + timedelta(minutes=5)
    if (now_ist() - last_end).total_seconds() / 60 > E["max_bar_age_min"]:
        return None, "NIFTY bars are stale"
    close = float(last["Close"])
    buf = E["breakout_buffer_pct"] / 100
    info = {"or_high": round(hi, 2), "or_low": round(lo, 2), "close": round(close, 2),
            "bar": bars.index[-1].strftime("%H:%M")}
    if close > hi * (1 + buf) and "CE" not in st["breakouts"]:
        return "CE", info
    if close < lo * (1 - buf) and "PE" not in st["breakouts"]:
        return "PE", info
    where = "inside" if lo <= close <= hi else ("above" if close > hi else "below")
    return None, {**info, "status": f"NIFTY {close:,.0f} is {where} the opening range {lo:,.0f}–{hi:,.0f}"}


def pick_contract(chain, expiry, side, spot):
    """Liquid contract by delta rule. Returns (chosen, candidates) - candidates are logged for comparison."""
    exp_dt = datetime.strptime(expiry, "%d-%b-%Y").replace(hour=15, minute=30, tzinfo=IST)
    yrs = max((exp_dt - now_ist()).total_seconds(), 60) / (365 * 86400)
    cands = []
    for r in chain["records"]["data"]:
        k = r.get("strikePrice")
        if k is None or abs(k - spot) > 6 * STEP:
            continue
        q = quote(chain, k, side)
        if validate(q, E["max_quote_age_min"]) or not q["iv"] or q["oi"] < E["min_oi"]:
            continue
        g = greeks(spot, k, yrs, q["iv"], side, R, Q)
        d = abs(g["delta"])
        if not (E["delta_min"] <= d <= E["delta_max"]):
            continue
        cands.append({"strike": k, "ask": q["ask"], "bid": q["bid"], "iv": q["iv"], "oi": q["oi"],
                      "delta": round(g["delta"], 3), "theta_lot": round(g["theta"] * LOT, 1),
                      "vega_lot": round(g["vega"] * LOT, 1), "spread_pct": round((q["ask"] - q["bid"]) / q["ask"] * 100, 2),
                      "kind": "ATM" if abs(k - spot) <= STEP / 2 else ("ITM" if (k < spot) == (side == "CE") else "OTM")})
    if not cands:
        return None, []
    target_delta = E["rule_delta"][E["contract_rule"]]
    chosen = min(cands, key=lambda c: (abs(abs(c["delta"]) - target_delta), c["spread_pct"]))
    return chosen, cands


def feasibility(c, now):
    """How much of the +target% the time decay would eat before the time exit, and the IV fall that
    would wipe it. Purely informational unless it exceeds max_theta_share."""
    hold_days = max((datetime.combine(now.date(), datetime.strptime(E["exit_by"], "%H:%M").time(), IST) - now)
                    .total_seconds(), 0) / 86400
    target_gain = c["ask"] * CONFIG["target_pct"] / 100 * LOT
    theta_cost = abs(c["theta_lot"]) * hold_days
    return {"target_gain_lot": round(target_gain), "theta_cost_to_exit": round(theta_cost),
            "theta_share": round(theta_cost / target_gain, 2) if target_gain else None,
            "iv_drop_to_erase_target": round(target_gain / c["vega_lot"], 2) if c["vega_lot"] else None,
            "nifty_move_needed": round(c["ask"] * CONFIG["target_pct"] / 100 / max(abs(c["delta"]), 0.05), 1)}


# ------------------------------------------------------------------- the loop
def close_position(st, price, result, basis, extra=None):
    """Two-phase close: 1) save the intent in state, 2) write result + ledger (both idempotent),
    3) clear the position. A crash between steps is finished by finish_closing() on the next tick."""
    p = st["position"]
    p["closing"] = {"price": round(price, 2), "result": result, "basis": basis,
                    "time": now_ist().isoformat(timespec="seconds"), "extra": extra or {}}
    save(st)
    finish_closing(st)


def finish_closing(st):
    p = st.get("position")
    if not p or not p.get("closing"):
        return
    c = p["closing"]
    qty = p["lots"] * LOT
    gross = (c["price"] - p["entry"]) * qty
    cost = charges(p["entry"], c["price"], qty)
    net = gross - cost
    row = {**{k: p.get(k) for k in TRADE_FIELDS}, "exit_time": c["time"], "exit": c["price"],
           "result": c["result"], "exit_basis": c["basis"], "gross_pnl": round(gross, 2),
           "charges": round(cost, 2), "net_pnl": round(net, 2), "pct": round((c["price"] / p["entry"] - 1) * 100, 2)}
    first = write_trade(row)
    if not ledger_has("exit", p["trade_id"]):
        event("exit", trade_id=p["trade_id"], result=c["result"], price=c["price"], basis=c["basis"],
              net=round(net, 2), **c["extra"])
    st["position"] = None
    if c["result"] in VERIFIED and net < 0:
        st["losses_today"] += 1
    save(st)
    if first:
        emoji = {"TARGET": "✅", "STOP": "❌", "TIME": "⏱"}.get(c["result"], "⚠️")
        note = "" if c["result"] in VERIFIED else " Not counted in results until checked against a real quote."
        notify(f"{emoji} NIFTY EXIT {c['result']}: {p['strike']} {p['side']}",
               f"Sell at ₹{c['price']:.2f} (bought ₹{p['entry']:.2f}). Net after charges ₹{net:+,.0f}. {c['basis']}.{note}",
               level="signal")


def new_day(st, today):
    if st["day"] == today:
        return
    finish_closing(st)
    if st.get("position"):  # never drop a position silently; price is unverified
        p = st["position"]
        close_position(st, p.get("last_bid") or p["entry"], "MISSED", "last valid bid (left open overnight)")
    if st.get("pending") and not ledger_has("unfilled", st["pending"]["trade_id"]):
        event("unfilled", trade_id=st["pending"]["trade_id"], reason="day ended")
    st.update(day=today, position=None, pending=None, trades_today=0, losses_today=0, breakouts=[],
              last_bar=None, rejects_today=0, status=None)


def fetch_quote(nse, item):
    """Network part of the exit watch - done WITHOUT holding the state lock."""
    try:
        chain = nse.chain(item["expiry"])
        q = quote(chain, item["strike"], item["side"])
        return q, validate(q, E["max_quote_age_min_exit"])
    except Exception as e:
        return None, f"fetch failed {e!r}"


def apply_quote(st, q, bad):
    """Fill / exit decisions for the pending order or open position, given a pre-fetched quote."""
    now = now_ist()
    hm = now.strftime("%H:%M")
    if st.get("pending"):
        o = st["pending"]
        # 1) timeout first: an expired order can never fill
        if (now - datetime.fromisoformat(o["signal_time"])).total_seconds() > E["fill_timeout_sec"]:
            reason = bad or f"ask {q['ask']} stayed above limit {o['limit']}"
            if not ledger_has("unfilled", o["trade_id"]):
                event("unfilled", trade_id=o["trade_id"], reason=reason)
            write_trade({**{k: o.get(k) for k in TRADE_FIELDS}, "result": "UNFILLED", "exit_basis": reason,
                         "net_pnl": 0, "gross_pnl": 0, "charges": 0})
            st["pending"] = None
            return
        # 2) a limit buy fills at ask + slippage but NEVER above the limit
        if not bad and q["ask"] <= o["limit"]:
            fill = round(min(q["ask"] + E["slippage_ticks"] * 0.05, o["limit"]), 2)
            p = {**o, "entry": fill, "fill_time": now.isoformat(timespec="seconds"),
                 "slippage": round(fill - o["signal_ask"], 2), "last_bid": q["bid"], "last_bid_time": q["nse_ts"],
                 "target": round(fill * (1 + CONFIG["target_pct"] / 100), 2),
                 "stop": round(fill * (1 - CONFIG["stop_pct"] / 100), 2), "mfe_pct": 0.0, "mae_pct": 0.0}
            st["position"], st["pending"] = p, None
            event("fill", trade_id=p["trade_id"], price=fill, quote=q)
            notify(f"{'📈' if p['side'] == 'CE' else '📉'} NIFTY BUY filled: {p['strike']} {p['side']} [{CONFIG['mode'].upper()}]",
                   f"Bought at ₹{fill:.2f} × {p['lots'] * LOT} ({p['expiry']}). Sell at ₹{p['target']:.2f} (+{CONFIG['target_pct']}%) "
                   f"or stop ₹{p['stop']:.2f} (-{CONFIG['stop_pct']}%), exit by {E['exit_by']}. "
                   f"Why: NIFTY closed {'above' if p['side'] == 'CE' else 'below'} its opening range "
                   f"{p['or_low']:,.0f}–{p['or_high']:,.0f}.", level="signal")
        return

    p = st.get("position")
    if not p:
        return
    if bad:
        st["rejects_today"] += 1
        event("quote_reject", trade_id=p["trade_id"], reason=bad)
        if hm >= E["exit_by"]:
            # we must exit but have no executable price: record as UNRESOLVED (excluded from results)
            close_position(st, p.get("last_bid") or p["entry"], "UNRESOLVED",
                           f"provisional: last valid bid from {p.get('last_bid_time', '?')} (quote rejected: {bad})")
        return
    bid = q["bid"]
    p["last_bid"], p["last_bid_time"] = bid, q["nse_ts"]
    pct = (bid / p["entry"] - 1) * 100
    p["mfe_pct"], p["mae_pct"] = round(max(p["mfe_pct"], pct), 2), round(min(p["mae_pct"], pct), 2)
    if bid <= p["stop"]:
        close_position(st, bid, "STOP", "NSE bid")
    elif bid >= p["target"]:
        close_position(st, bid, "TARGET", "NSE bid")
    elif hm >= E["exit_by"]:
        close_position(st, bid, "TIME", "NSE bid")


def watch(nse, st):
    """Single-threaded helper (used by tests): fetch then apply."""
    item = st.get("position") or st.get("pending")
    if item:
        q, bad = fetch_quote(nse, item)
        apply_quote(st, q, bad)


def reconcile():
    """Settle UNRESOLVED/MISSED exits from our own recorded quotes: first valid bid within 10 min after the exit."""
    if not TRADES.exists():
        return 0
    with TRADES.open() as f:
        rows = list(csv.DictReader(f))
    fixed = 0
    for r in rows:
        if r["result"] != "UNRESOLVED" or not r.get("exit_time"):
            continue
        t0 = datetime.fromisoformat(r["exit_time"])
        f = QUOTES_DIR / f"{t0:%Y-%m-%d}.csv.gz"
        if not f.exists():
            continue
        exp_key = datetime.strptime(r["expiry"], "%d-%b-%Y").strftime("%d-%m-%Y")
        with gzip.open(f, "rt") as g:
            for qr in csv.DictReader(g):
                if qr["strike"] != str(r["strike"]).split(".")[0] and float(qr["strike"]) != float(r["strike"]):
                    continue
                if qr["side"] != r["side"] or qr["expiry"] != exp_key:
                    continue
                qt = datetime.fromisoformat(qr["poll_ts"])
                if not (t0 <= qt <= t0 + timedelta(minutes=10)):
                    continue
                qq = {"bid": float(qr["bid"] or 0), "ask": float(qr["ask"] or 0), "nse_ts": qr["nse_ts"]}
                age = None
                try:
                    age = (qt - datetime.strptime(qr["nse_ts"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)).total_seconds() / 60
                except ValueError:
                    pass
                if age is None or age > E["max_quote_age_min_exit"] or qq["bid"] <= 0 or qq["ask"] < qq["bid"]:
                    continue
                price, qty = qq["bid"], LOT  # engine trades are 1 lot
                entry = float(r["entry"])
                gross = (price - entry) * qty
                cost = charges(entry, price, qty)
                r.update(exit=round(price, 2), result="TIME", exit_basis=f"reconciled from recorded NSE bid at {qr['nse_ts']}",
                         gross_pnl=round(gross, 2), charges=round(cost, 2), net_pnl=round(gross - cost, 2),
                         pct=round((price / entry - 1) * 100, 2))
                event("reconciled", trade_id=r["trade_id"], price=price, quote_time=qr["nse_ts"])
                fixed += 1
                break
    if fixed:
        rewrite_trades(rows)
    return fixed


def look_for_signal(nse, st, bars=None, prefetched=None):
    """Signal decision. Network data can be pre-fetched outside the lock and passed in."""
    now = now_ist()
    hm = now.strftime("%H:%M")
    if st.get("position") or st.get("pending"):
        return
    if bars is None:
        bars = nifty_bars()
    if bars is not None and not bars.empty:
        bar = bars.index[-1].isoformat()
        if bar == st.get("last_bar"):
            return  # judge each completed bar once
        st["last_bar"] = bar
    side, info = orb_signal(bars, st)
    st["status"] = info if isinstance(info, dict) else {"status": info}
    if not side:
        return
    st["breakouts"].append(side)  # a direction triggers once a day, traded or not
    block = (None if E["entry_start"] <= hm <= E["entry_end"] else f"outside entry window {E['entry_start']}-{E['entry_end']}")
    if not block and st["trades_today"] >= E["max_trades_per_day"]:
        block = "daily trade limit reached"
    if not block and st["losses_today"] >= E["max_losses_per_day"]:
        block = "loss limit reached for today"
    expiry, chain = prefetched if prefetched else (None, None)
    if chain is None:
        expiry = pick_expiry(nse.expiries())
        chain = nse.chain(expiry)
    spot = chain["records"]["underlyingValue"]
    c, cands = (None, []) if block else pick_contract(chain, expiry, side, spot)
    if not block and not c:
        block = "no liquid contract with valid quote and delta in range"
    feas = feasibility(c, now) if c else None
    if not block and feas["theta_share"] is not None and feas["theta_share"] > E["max_theta_share"]:
        block = f"time decay to {E['exit_by']} would eat {feas['theta_share']:.0%} of the target"
    if not block and c["ask"] * LOT > CONFIG["capital_per_trade"]:
        block = f"1 lot costs ₹{c['ask'] * LOT:,.0f}, above budget"
    tid = now.strftime("%Y%m%d-%H%M") + side
    event("signal", trade_id=tid, side=side, info=info, spot=spot, expiry=expiry, chosen=c, candidates=cands,
          feasibility=feas, blocked=block, rule=E["contract_rule"])
    if block:
        st["status"] = {**info, "status": f"{side} breakout at {info['bar']}, not traded: {block}"}
        log(f"engine: {side} breakout not traded: {block}")
        return
    days = (datetime.strptime(expiry, "%d-%b-%Y").date() - now.date()).days
    st["pending"] = {"trade_id": tid, "signal_time": now.isoformat(timespec="seconds"), "side": side,
                     "strike": c["strike"], "expiry": expiry, "days_to_expiry": days, "lots": 1,
                     "limit": c["ask"], "signal_ask": c["ask"], "entry_delta": c["delta"],
                     "entry_theta_lot": c["theta_lot"], "entry_iv": c["iv"], "spot_at_signal": spot,
                     "or_high": info["or_high"], "or_low": info["or_low"], "hour": now.hour,
                     "rule": E["contract_rule"], "feasibility": feas}
    st["trades_today"] += 1
    event("order", trade_id=tid, limit=c["ask"], strike=c["strike"], side=side)
    log(f"engine: {side} breakout -> limit buy {c['strike']}{side} @ {c['ask']}")


def pick_expiry(expiries):
    today = now_ist().date()
    return next((e for e in expiries if (datetime.strptime(e, "%d-%b-%Y").date() - today).days
                 >= E["min_days_to_expiry"]), expiries[0])


def market_hours(now):
    return now.weekday() < 5 and "09:15" <= now.strftime("%H:%M") <= "15:31"


def exit_tick(nse):
    """Fast path: one NSE request, then a short locked update."""
    with locked():
        st = load()
        new_day(st, now_ist().date().isoformat())
        finish_closing(st)  # complete any interrupted close
        save(st)
    item = st.get("position") or st.get("pending")
    if item:
        q, bad = fetch_quote(nse, item)
        with locked():
            st = load()
            cur = st.get("position") or st.get("pending")
            if cur and cur["trade_id"] == item["trade_id"]:
                apply_quote(st, q, bad)
            st["heartbeat_exit"] = now_ist().isoformat(timespec="seconds")
            save(st)
    else:
        with locked():
            st = load()
            st["heartbeat_exit"] = now_ist().isoformat(timespec="seconds")
            save(st)


def signal_tick(nse):
    """Slow path: Yahoo bars + chain fetched without the lock; decision under the lock; quotes recorded."""
    st0 = load()
    flat = not (st0.get("position") or st0.get("pending"))
    exp = (st0.get("position") or st0.get("pending") or {}).get("expiry") or pick_expiry(nse.expiries())
    chain = nse.chain(exp)
    bars = nifty_bars() if flat else None
    if E["record_quotes"]:
        record_quotes(chain)
    if flat:
        with locked():
            st = load()
            new_day(st, now_ist().date().isoformat())
            look_for_signal(nse, st, bars=bars, prefetched=(exp, chain))
            st["heartbeat_signal"] = now_ist().isoformat(timespec="seconds")
            save(st)
    reconcile()


def step(nse):
    """One full cycle (used by --once and tests)."""
    exit_tick(nse)
    signal_tick(nse)


def _loop(name, fn, every, stop):
    from scanner import NSE
    nse, made = None, 0
    while not stop.is_set():
        now = now_ist()
        if not market_hours(now):
            if now.strftime("%H:%M") > "15:31" or now.weekday() >= 5:
                stop.set()
                return
            stop.wait(30)
            continue
        t0 = time.time()
        try:
            if nse is None or time.time() - made > 600:
                nse, made = NSE(), time.time()
            fn(nse)
        except Exception as e:
            log(f"engine {name}: failed {e!r}")
            event("error", where=name, error=repr(e))
            nse = None
        stop.wait(max(1, every - (time.time() - t0)))


def run_monitor(once=False):
    import threading
    log("engine: monitor started")
    if once:
        from scanner import NSE
        step(NSE())
        return
    stop = threading.Event()
    t_exit = threading.Thread(target=_loop, args=("exits", exit_tick, E["poll_sec"], stop), daemon=True)
    t_sig = threading.Thread(target=_loop, args=("signals", signal_tick, E["signal_sec"], stop), daemon=True)
    t_exit.start()
    t_sig.start()
    try:
        while t_exit.is_alive() or t_sig.is_alive():
            t_exit.join(5)
    except KeyboardInterrupt:
        stop.set()
    log("engine: market closed, monitor exiting")


# -------------------------------------------------------------------- metrics
def metrics():
    rows = []
    if TRADES.exists():
        with TRADES.open() as f:
            rows = list(csv.DictReader(f))
    filled = [r for r in rows if r["result"] in VERIFIED]  # only exits priced from a validated bid
    nets = [float(r["net_pnl"]) for r in filled]
    wins, losses = [n for n in nets if n > 0], [n for n in nets if n <= 0]
    wr = len(wins) / len(nets) if nets else None
    aw = sum(wins) / len(wins) if wins else 0
    al = -sum(losses) / len(losses) if losses else 0
    cum, peak, dd, streak, worst = 0, 0, 0, 0, 0
    for n in nets:
        cum += n
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        streak = streak + 1 if n <= 0 else 0
        worst = max(worst, streak)

    def by(key, fn):
        out = {}
        for r in filled:
            k = fn(r[key])
            out.setdefault(k, []).append(float(r["net_pnl"]))
        return {k: {"n": len(v), "net": round(sum(v)), "exp": round(sum(v) / len(v))} for k, v in sorted(out.items())}

    events = []
    if LEDGER.exists():
        with LEDGER.open() as f:
            events = [json.loads(l) for l in f if l.strip()]
    return {
        "signals": sum(1 for e in events if e["event"] == "signal"),
        "blocked": sum(1 for e in events if e["event"] == "signal" and e.get("blocked")),
        "orders": sum(1 for e in events if e["event"] == "order"),
        "unfilled": sum(1 for r in rows if r["result"] == "UNFILLED"),
        "rejected_quotes": sum(1 for e in events if e["event"] == "quote_reject"),
        "missed_exits": sum(1 for r in rows if r["result"] == "MISSED"),
        "unresolved": sum(1 for r in rows if r["result"] == "UNRESOLVED"),
        "trades": len(nets), "win_rate": round(wr * 100, 1) if wr is not None else None,
        "avg_win": round(aw), "avg_loss": round(al),
        "expectancy": round(wr * aw - (1 - wr) * al) if wr is not None else None,
        "net_total": round(sum(nets)), "max_drawdown": round(dd), "worst_streak": worst,
        "avg_slippage": round(sum(float(r["slippage"] or 0) for r in filled) / len(filled), 2) if filled else None,
        "by_hour": by("hour", lambda h: f"{int(h):02d}:00"),
        "by_expiry": by("days_to_expiry", lambda d: "0-2 days" if int(d) <= 2 else "3-5 days" if int(d) <= 5 else "6+ days"),
        "by_iv": by("entry_iv", lambda v: "IV <14" if float(v) < 14 else "IV 14-18" if float(v) < 18 else "IV 18+"),
        "rows": rows[-50:],
    }


def report():
    m = metrics()
    print(f"NIFTY engine (rule: opening-range breakout, {E['contract_rule']} contract)")
    print(f"  signals {m['signals']} (blocked {m['blocked']}), orders {m['orders']}, unfilled {m['unfilled']}, "
          f"rejected quotes {m['rejected_quotes']}, missed exits {m['missed_exits']}, unresolved {m['unresolved']} (excluded)")
    if not m["trades"]:
        print("  no filled trades yet")
        return
    print(f"  trades {m['trades']}  win rate {m['win_rate']}%  avg win ₹{m['avg_win']:,}  avg loss ₹{m['avg_loss']:,}")
    print(f"  EXPECTANCY ₹{m['expectancy']:,} per trade  |  net ₹{m['net_total']:,}  |  max drawdown ₹{m['max_drawdown']:,}"
          f"  |  worst losing streak {m['worst_streak']}  |  avg slippage ₹{m['avg_slippage']}")
    for name in ("by_hour", "by_expiry", "by_iv"):
        print("  " + name + ": " + ", ".join(f"{k} n={v['n']} exp ₹{v['exp']}" for k, v in m[name].items()))
