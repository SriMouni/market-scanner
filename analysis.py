"""Chart checks (candlesticks + indicators) and company-health scores.

chart_check(ohlcv, side, kind)  -> 5 plain-language checks + verdict for a CE (up) / PE (down) idea
fundamentals(symbols, sectors) -> company health score 0-100 with plain-language bullets (cached 7 days)
"""
import math
import time

import pandas as pd

from common import DATA, log, read_json, write_json

FUND_CACHE = DATA / "fundamentals.json"
FIN_SECTORS = {"Financial Services", "Banks"}


# ================================================================ indicators
def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, 1e-9))


def macd_hist(close):
    m = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    return m - m.ewm(span=9, adjust=False).mean()


def candle_pattern(o, h, l, c):
    """Name of the pattern on the last candle (uses the one before it too)."""
    o1, h1, l1, c1 = o[-1], h[-1], l[-1], c[-1]
    o0, c0 = o[-2], c[-2]
    rng = max(h1 - l1, 1e-9)
    body = abs(c1 - o1)
    upper, lower = h1 - max(o1, c1), min(o1, c1) - l1
    if c0 < o0 and c1 > o1 and c1 >= o0 and o1 <= c0:
        return "bullish engulfing", +1
    if c0 > o0 and c1 < o1 and c1 <= o0 and o1 >= c0:
        return "bearish engulfing", -1
    if body <= 0.1 * rng:
        return "doji (indecision)", 0
    if lower >= 2 * body and upper <= 0.6 * body + 0.1 * rng:
        return "hammer (buyers stepped in)", +1
    if upper >= 2 * body and lower <= 0.6 * body + 0.1 * rng:
        return "shooting star (sellers stepped in)", -1
    if body >= 0.8 * rng:
        return ("strong green candle", +1) if c1 > o1 else ("strong red candle", -1)
    return ("green candle", 0) if c1 >= o1 else ("red candle", 0)


def chart_check(df, side, kind="daily"):
    """df: DataFrame with Open/High/Low/Close/Volume (oldest first). side CE=up idea, PE=down idea.
    kind 'daily' (daily candles) or 'intraday' (5-min candles)."""
    df = df.dropna(subset=["Close"])
    if len(df) < 30:
        return None
    if kind == "intraday" and len(df) > 3:
        df = df.iloc[:-1]  # last 5-min bar may still be forming
    c, o, h, l = df["Close"], df["Open"], df["High"], df["Low"]
    up = side == "CE"
    price = float(c.iloc[-1])
    ema20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
    r = float(rsi(c).iloc[-1])
    mh = macd_hist(c)
    mh_now, mh_prev = float(mh.iloc[-1]), float(mh.iloc[-2])
    name, sign = candle_pattern(o.values, h.values, l.values, c.values)
    look = 20 if kind == "daily" else 75  # ~20 days, or ~1 day of 5-min bars
    res = float(h.iloc[-look - 1:-1].max())
    sup = float(l.iloc[-look - 1:-1].min())
    avg = "20-day average" if kind == "daily" else "recent average"
    room_need = 1.0 if kind == "daily" else 0.5

    checks = []
    trend_ok = price > ema20 if up else price < ema20
    checks.append({"name": "Direction", "ok": trend_ok, "tech": "trend",
                   "text": (f"Overall the price is moving {'up' if price > ema20 else 'down'}, "
                            + ("the same way as this idea" if trend_ok else "the opposite way to this idea"))})
    if up:
        rsi_ok = 50 <= r <= 72
        rsi_txt = ("It has gone up a lot very fast and may fall back a little first" if r > 72 else
                   "Not much buying energy yet" if r < 50 else "Rising at a healthy pace, not overheated")
    else:
        rsi_ok = 28 <= r <= 50
        rsi_txt = ("It has fallen a lot very fast and may bounce back a little first" if r < 28 else
                   "Not much selling energy yet" if r > 50 else "Falling at a steady pace, not overdone")
    checks.append({"name": "Speed", "ok": rsi_ok, "text": rsi_txt, "tech": f"RSI {r:.0f}", "value": round(r, 1)})
    macd_ok = (mh_now > 0 and mh_now >= mh_prev) if up else (mh_now < 0 and mh_now <= mh_prev)
    checks.append({"name": "Who's winning", "ok": macd_ok, "tech": "MACD",
                   "text": ("Buyers are winning and getting stronger" if mh_now > 0 and mh_now >= mh_prev else
                            "Buyers are winning but getting tired" if mh_now > 0 else
                            "Sellers are winning and getting stronger" if mh_now <= mh_prev else
                            "Sellers are winning but getting tired")})
    # ok = a candle pointing our way, or a plain candle that isn't indecision / against us
    candle_ok = (sign > 0 if up else sign < 0) or (sign == 0 and "doji" not in name)
    plain = {"bullish engulfing": "buyers took over from sellers", "bearish engulfing": "sellers took over from buyers",
             "doji (indecision)": "buyers and sellers were evenly matched, no clear winner",
             "hammer (buyers stepped in)": "the price dipped but buyers pushed it back up",
             "shooting star (sellers stepped in)": "the price jumped but sellers pushed it back down",
             "strong green candle": "buyers were firmly in charge", "strong red candle": "sellers were firmly in charge",
             "green candle": "the price closed a bit higher", "red candle": "the price closed a bit lower"}[name]
    period = "day" if kind == "daily" else "5 minutes"
    checks.append({"name": "Last move", "ok": candle_ok, "text": f"In the last {period}, {plain}",
                   "tech": f"candle: {name.split(' (')[0]}", "pattern": name})
    if up:
        broke = price > res
        room = (res / price - 1) * 100
        room_ok = broke or room >= room_need
        room_txt = (f"It just went above ₹{res:,.1f}, a level where it kept stopping before. Often a good sign" if broke else
                    f"There's room to rise before ₹{res:,.1f}, where it stopped before ({room:.1f}% away)" if room_ok else
                    f"It's close to ₹{res:,.1f}, where it stopped before (only {room:.1f}% away), so little room to rise")
    else:
        broke = price < sup
        room = (1 - sup / price) * 100
        room_ok = broke or room >= room_need
        room_txt = (f"It just fell below ₹{sup:,.1f}, a level where it kept bouncing before. Often a sign of more fall" if broke else
                    f"There's room to fall before ₹{sup:,.1f}, where it bounced before ({room:.1f}% away)" if room_ok else
                    f"It's close to ₹{sup:,.1f}, where it bounced before (only {room:.1f}% away), so little room to fall")
    checks.append({"name": "Room to move", "ok": room_ok, "text": room_txt, "tech": "support/resistance"})

    passed = sum(1 for x in checks if x["ok"])
    reversal = (sign < 0 and up) or (sign > 0 and not up)
    extreme = (r > 80 and up) or (r < 20 and not up)
    verdict = "against" if (reversal or extreme) else "strong" if passed >= 4 else "ok" if passed == 3 else "weak"
    return {"checks": checks, "passed": passed, "verdict": verdict, "rsi": round(r, 1),
            "pattern": name, "resistance": round(res, 2), "support": round(sup, 2)}


# ============================================================== fundamentals
def _pts(v, cuts):
    """cuts: [(threshold, points), ...] best first; value >= threshold earns points."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    for t, p in cuts:
        if v >= t:
            return p
    return 2


def _cagr(series):
    s = [float(x) for x in series if x is not None and not pd.isna(x)]
    if len(s) < 2 or s[-1] <= 0 or s[0] <= 0:
        return None
    yrs = len(s) - 1
    return ((s[0] / s[-1]) ** (1 / yrs) - 1) * 100  # newest first in Yahoo statements


def fetch_one(sym):
    import yfinance as yf
    t = yf.Ticker(sym + ".NS")
    i = t.info or {}
    out = {k: i.get(k) for k in ("trailingPE", "priceToBook", "returnOnEquity", "returnOnAssets", "debtToEquity",
                                 "profitMargins", "operatingMargins", "revenueGrowth", "earningsGrowth",
                                 "heldPercentInsiders", "dividendYield", "marketCap")}
    try:
        inc = t.income_stmt
        if inc is not None and not inc.empty:
            if "Net Income" in inc.index:
                out["profit_cagr"] = _cagr(list(inc.loc["Net Income"].values))
                out["profit_history"] = [[str(c.date()), float(v)] for c, v in inc.loc["Net Income"].items() if not pd.isna(v)]
            if "Total Revenue" in inc.index:
                out["revenue_cagr"] = _cagr(list(inc.loc["Total Revenue"].values))
    except Exception:
        pass
    out["fetched"] = time.time()
    return out


def fundamentals(symbols, sectors):
    """symbols: list; sectors: {symbol: sector}. Returns {symbol: health dict}."""
    cache = read_json(FUND_CACHE, {})
    for s in symbols:
        if s not in cache or time.time() - cache[s].get("fetched", 0) > 7 * 86400:
            try:
                cache[s] = fetch_one(s)
            except Exception as e:
                log(f"fundamentals: {s} failed {e!r}")
    write_json(FUND_CACHE, cache)

    pe_by_sector = {}
    for s in symbols:
        pe = (cache.get(s) or {}).get("trailingPE")
        if pe and pe > 0:
            pe_by_sector.setdefault(sectors.get(s, "Other"), []).append(pe)
    med = {k: sorted(v)[len(v) // 2] for k, v in pe_by_sector.items()}

    out = {}
    for s in symbols:
        f = cache.get(s)
        if not f:
            continue
        sec = sectors.get(s, "Other")
        fin = sec in FIN_SECTORS
        pts, good, bad = {}, [], []
        roe, roa = f.get("returnOnEquity"), f.get("returnOnAssets")
        if fin and roa is not None:
            pts["Profitability"] = _pts(roa * 100, [(1.5, 20), (1.0, 14), (0.6, 8)])
            (good if roa * 100 >= 1.0 else bad).append(f"Earns ₹{roa * 100:.1f} profit a year on every ₹100 it lends and holds ({'good' if roa * 100 >= 1 else 'low'} for a bank)")
        elif roe is not None:
            pts["Profitability"] = _pts(roe * 100, [(18, 20), (12, 14), (8, 8)])
            (good if roe * 100 >= 12 else bad).append(f"Makes ₹{roe * 100:.0f} profit a year for every ₹100 of the owners' money ({'very good' if roe * 100 >= 18 else 'good' if roe * 100 >= 12 else 'low'})")
        pc = f.get("profit_cagr")
        pts["Growth"] = _pts(pc, [(20, 20), (12, 14), (5, 8)]) if pc is not None else None
        if pc is not None:
            yrs = len(f.get("profit_history", [])) - 1
            (good if pc >= 10 else bad).append(
                f"Profit stayed about the same over the last {yrs} years" if abs(pc) < 1 else
                f"Profit {'grew' if pc > 0 else 'fell'} about {abs(pc):.0f}% every year for the last {yrs} years")
        de = f.get("debtToEquity")
        if not fin and de is not None:
            ratio = de / 100
            pts["Debt"] = _pts(-ratio, [(-0.3, 20), (-0.8, 14), (-1.5, 8)])
            (good if ratio <= 0.8 else bad).append(f"Has borrowed ₹{ratio * 100:.0f} for every ₹100 of its own money ({'low, safe' if ratio <= 0.3 else 'manageable' if ratio <= 0.8 else 'high, riskier'})")
        pe = f.get("trailingPE")
        if pe and pe > 0 and med.get(sec):
            rel = pe / med[sec]
            pts["Valuation"] = _pts(-rel, [(-0.8, 20), (-1.2, 14), (-1.8, 8)])
            txt = f"Share price is {pe:.0f}× its yearly profit per share; similar companies are {med[sec]:.0f}×"
            (good if rel <= 1.2 else bad).append(txt + (" (cheaper than similar companies)" if rel <= 0.8 else " (fairly priced)" if rel <= 1.2 else " (expensive compared with similar companies)"))
        elif pe is None or (pe is not None and pe <= 0):
            pts["Valuation"] = 2
            bad.append("Not making a profit right now (or data missing)")
        om = f.get("profitMargins") if fin else f.get("operatingMargins")
        if om is not None:
            pts["Margins"] = _pts(om * 100, [(20, 20), (12, 14), (6, 8)])
            (good if om * 100 >= 12 else bad).append(f"Keeps about ₹{om * 100:.0f} as profit from every ₹100 of sales ({'good' if om * 100 >= 12 else 'thin'})")
        valid = [v for v in pts.values() if v is not None]
        if len(valid) < 3:
            continue
        score = round(sum(valid) / (20 * len(valid)) * 100)
        promo = f.get("heldPercentInsiders")
        info = []
        if promo is not None and promo > 0.01:
            info.append(f"The founders/owner family hold {promo * 100:.0f}% of the company")
        out[s] = {"health": score, "grade": "Strong" if score >= 70 else "Average" if score >= 50 else "Weak",
                  "good": good, "bad": bad, "info": info, "parts": pts,
                  "pe": round(pe, 1) if pe else None, "sector_pe": round(med.get(sec), 1) if med.get(sec) else None,
                  "pb": round(f["priceToBook"], 1) if f.get("priceToBook") else None,
                  "roe": round(roe * 100, 1) if roe is not None else None,
                  "debt_equity": round(de / 100, 2) if de is not None and not fin else None,
                  "profit_cagr": round(pc, 1) if pc is not None else None,
                  "revenue_cagr": round(f["revenue_cagr"], 1) if f.get("revenue_cagr") is not None else None,
                  "div_yield": round(f["dividendYield"], 2) if f.get("dividendYield") else None,
                  "mcap_cr": round(f["marketCap"] / 1e7) if f.get("marketCap") else None,
                  "profit_history": f.get("profit_history", [])}
    return out
