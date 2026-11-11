"""End-of-day scan (run after ~7 PM IST) using NSE's official daily bhavcopy files.

1. Grade yesterday's option picks against today's prices (track record).
2. New option picks for the next session across all F&O stocks + indices,
   using futures price/OI build-up confirmed by the 20-day trend.
3. Long-term watchlist from NIFTY 50 + NIFTY Next 50 (trend + momentum screen).
"""
import io
import math
import zipfile
from datetime import datetime, timedelta

import pandas as pd
import requests

from common import (CONFIG, DATA, IST, UA, append_csv, bs_price, charges, greeks, implied_vol, log,
                    now_ist, read_csv, read_json, write_json)
from notify import notify

D = CONFIG["daily"]
R = CONFIG["risk_free_rate"]
BHAV_DIR = DATA / "bhav"
BHAV_DIR.mkdir(exist_ok=True)
PENDING = DATA / "daily_pending.json"
RESULTS = DATA / "daily_results.csv"
OUT = DATA / "daily.json"
ARCH = "https://nsearchives.nseindia.com/content"
YAHOO_INDEX = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}

http = requests.Session()
http.headers.update({"User-Agent": UA, "Accept": "*/*"})


# ---------------------------------------------------------------- downloads
def fetch_fo(day):
    """Return F&O bhavcopy DataFrame for a date, or None if NSE has no file (holiday)."""
    key = day.strftime("%Y%m%d")
    cache = BHAV_DIR / f"fo_{key}.csv.gz"
    if cache.exists():
        return pd.read_csv(cache)
    url = f"{ARCH}/fo/BhavCopy_NSE_FO_0_0_0_{key}_F_0000.csv.zip"
    r = http.get(url, timeout=60)
    if r.status_code != 200 or not r.content.startswith(b"PK"):
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        df = pd.read_csv(z.open(z.namelist()[0]))
    df.to_csv(cache, index=False, compression="gzip")
    for old in sorted(BHAV_DIR.glob("fo_*.csv.gz"))[:-5]:  # keep last 5 days
        old.unlink()
    return df


def latest_fo():
    now = now_ist()
    day = now.date() if now.strftime("%H:%M") >= "18:30" else now.date() - timedelta(days=1)
    for _ in range(10):
        if day.weekday() < 5:
            df = fetch_fo(day)
            if df is not None:
                return day, df
        day -= timedelta(days=1)
    raise RuntimeError("no NSE F&O bhavcopy found in last 10 days")


def ban_list():
    try:
        r = http.get(f"{ARCH}/fo/fo_secban.csv", timeout=30)
        return {l.split(",")[-1].strip() for l in r.text.splitlines()[1:] if l.strip()}
    except Exception:
        return set()


def index_members():
    """NIFTY 500 companies, tagged Large cap (NIFTY 50 / Next 50) or Mid/Small cap."""
    syms, seen = [], set()
    for name in ("nifty50", "niftynext50", "nifty500"):
        cache = DATA / f"ind_{name}list.csv"
        if not cache.exists() or (datetime.now().timestamp() - cache.stat().st_mtime) > 7 * 86400:
            r = http.get(f"{ARCH}/indices/ind_{name}list.csv", timeout=30)
            if r.ok and "Symbol" in r.text:
                cache.write_text(r.text)
        if cache.exists():
            df = pd.read_csv(cache)
            tag = "Large cap" if name in ("nifty50", "niftynext50") else "Mid/Small cap"
            for s, n, ind in zip(df["Symbol"], df["Company Name"], df["Industry"]):
                if s not in seen and not str(s).upper().startswith("DUMMY"):
                    seen.add(s)
                    syms.append((s, n, tag, ind))
    return syms


def yahoo_ohlc(tickers, period):
    """Daily candles; returns {ticker: DataFrame(Open, High, Low, Close, Volume)}."""
    import yfinance as yf
    if not tickers:
        return {}
    df = yf.download(tickers, period=period, progress=False, auto_adjust=True, threads=True)
    out = {}
    for t in tickers:
        try:
            f = df.xs(t, axis=1, level=1) if isinstance(df.columns, pd.MultiIndex) else df
            f = f.dropna(subset=["Close"])
            if not f.empty:
                out[t] = f
        except KeyError:
            pass
    return out


def yahoo_closes(tickers, period):
    import yfinance as yf
    if not tickers:
        return pd.DataFrame()
    def get(tks):
        df = yf.download(tks, period=period, progress=False, auto_adjust=True, threads=True)
        if isinstance(df.columns, pd.MultiIndex):
            return df["Close"]
        return df[["Close"]].rename(columns={"Close": tks[0]})

    closes = get(tickers)
    missing = [t for t in tickers if t not in closes or closes[t].dropna().empty]
    if missing:  # Yahoo drops a few tickers on network hiccups - retry once
        import time
        time.sleep(3)
        again = get(missing)
        for t in missing:
            if t in again and not again[t].dropna().empty:
                closes[t] = again[t]
    return closes


# -------------------------------------------------------------- grading
def grade_pending(day, fo):
    pend = read_json(PENDING, None)
    if not pend or pend["date"] >= day.isoformat():
        return
    log(f"daily: grading {len(pend['picks'])} picks from {pend['date']} on {day}")
    for p in pend["picks"]:
        row = fo[(fo["TckrSymb"] == p["symbol"]) & (fo["XpryDt"] == p["expiry"]) &
                 (fo["StrkPric"] == p["strike"]) & (fo["OptnTp"] == p["side"])]
        res = {"pick_date": pend["date"], "trade_date": day.isoformat(), "symbol": p["symbol"],
               "contract": p["contract"], "side": p["side"], "ref_price": p["entry"], "lot": p["lot"]}
        if row.empty or float(row.iloc[0]["OpnPric"]) <= 0:
            append_csv(RESULTS, {**res, "entry": "", "exit": "", "result": "NO FILL", "pct": 0, "net_pnl": 0})
            continue
        o, h, l, c = (float(row.iloc[0][k]) for k in ("OpnPric", "HghPric", "LwPric", "ClsPric"))
        if abs(o / p["entry"] - 1) * 100 > D["gap_skip_pct"]:
            append_csv(RESULTS, {**res, "entry": o, "exit": "", "result": "SKIP GAP", "pct": 0, "net_pnl": 0})
            continue
        tgt, sl = o * (1 + CONFIG["target_pct"] / 100), o * (1 - CONFIG["stop_pct"] / 100)
        if l <= sl:            # if both touched we can't know which came first: assume the stop
            result, exit_ = "STOP", sl
        elif h >= tgt:
            result, exit_ = "TARGET", tgt
        else:
            result, exit_ = "CLOSE", c
        net = (exit_ - o) * p["lot"] - charges(o, exit_, p["lot"])
        append_csv(RESULTS, {**res, "entry": round(o, 2), "exit": round(exit_, 2), "result": result,
                             "pct": round((exit_ - o) / o * 100, 2), "net_pnl": round(net, 2)})
    PENDING.unlink()


# ------------------------------------------------------------ option picks
def buildups(fo, banned):
    fut = fo[fo["FinInstrmTp"].isin(["STF", "IDF"])].copy()
    fut = fut.sort_values("XpryDt").groupby("TckrSymb", as_index=False).first()  # near month
    fut["price_chg"] = (fut["ClsPric"] / fut["PrvsClsgPric"] - 1) * 100
    prev_oi = fut["OpnIntrst"] - fut["ChngInOpnIntrst"]
    fut["oi_chg"] = (fut["ChngInOpnIntrst"] / prev_oi.where(prev_oi > 0)) * 100
    fut = fut[fut["TckrSymb"].isin(list(YAHOO_INDEX)) |
              fut["TtlTrfVal"].rank(ascending=False).le(D["universe_top_n"])]
    fut = fut[~fut["TckrSymb"].isin(banned)]

    def kind(r):
        up, oi_up = r.price_chg >= D["price_chg_min"], r.oi_chg >= D["oi_chg_min"]
        dn = r.price_chg <= -D["price_chg_min"]
        if up and oi_up:
            return "Long build-up"
        if dn and oi_up:
            return "Short build-up"
        return None

    fut["buildup"] = fut.apply(kind, axis=1)
    fut = fut[fut["buildup"].notna()].copy()
    fut["score"] = fut["price_chg"].abs() + fut["oi_chg"] / 5
    return fut.sort_values("score", ascending=False)


def pick_option(fo, symbol, side, spot, day):
    is_index = symbol in YAHOO_INDEX
    opts = fo[(fo["TckrSymb"] == symbol) & (fo["OptnTp"] == side) &
              fo["FinInstrmTp"].isin(["STO", "IDO"])].copy()
    min_days = D["min_days_to_expiry_index"] if is_index else D["min_days_to_expiry_stock"]
    exps = sorted(e for e in opts["XpryDt"].unique()
                  if (datetime.strptime(e, "%Y-%m-%d").date() - day).days >= min_days)
    if not exps:
        return None
    expiry = exps[0]
    yrs = (datetime.strptime(expiry, "%Y-%m-%d").date() - day).days / 365
    best = None
    for _, o in opts[opts["XpryDt"] == expiry].iterrows():
        px, k = float(o["ClsPric"]), float(o["StrkPric"])
        if px < D["min_premium"] or o["TtlTradgVol"] < D["min_contracts_traded"]:
            continue
        iv = implied_vol(px, spot, k, yrs, side, R)
        if not iv:
            continue
        g = greeks(spot, k, yrs, iv, side, R)
        if not (CONFIG["intraday"]["delta_min"] <= abs(g["delta"]) <= CONFIG["intraday"]["delta_max"]):
            continue
        if best is None or abs(abs(g["delta"]) - 0.5) < abs(abs(best["delta"]) - 0.5):
            lot = int(o["NewBrdLotQty"])
            best = {"expiry": expiry, "strike": k, "entry": px, "iv": round(iv, 1),
                    "delta": round(g["delta"], 2), "theta_lot": round(g["theta"] * lot),
                    "gamma": g["gamma"], "vega_lot": round(g["vega"] * lot),
                    "days": (datetime.strptime(expiry, "%Y-%m-%d").date() - day).days,
                    "years": yrs, "lot": lot, "oi": int(o["OpnIntrst"]),
                    "oi_chg": int(o["ChngInOpnIntrst"]), "volume": int(o["TtlTradgVol"]),
                    "opt_chg": round((px / float(o["PrvsClsgPric"]) - 1) * 100, 1) if float(o["PrvsClsgPric"]) > 0 else None}
    return best


def make_picks(fo, day, banned):
    cands = buildups(fo, banned)
    syms = cands["TckrSymb"].head(D["max_candidates"]).tolist()
    tick = {s: YAHOO_INDEX.get(s, s + ".NS") for s in syms}
    trend, candles = {}, {}
    try:
        data = yahoo_ohlc(list(tick.values()), "6mo")
        for s, t in tick.items():
            if t in data:
                f = data[t][data[t].index.date <= day]
                candles[s] = f
                if len(f) >= 20:
                    trend[s] = (float(f["Close"].iloc[-1]), float(f["Close"].tail(20).mean()))
    except Exception as e:
        log(f"daily: yahoo trend check failed {e!r}")
    from analysis import chart_check

    picks, per_side = [], {"CE": 0, "PE": 0}
    for _, f in cands.head(D["max_candidates"]).iterrows():
        s = f["TckrSymb"]
        side = "CE" if f["buildup"] == "Long build-up" else "PE"
        if per_side[side] >= D["picks_per_side"]:
            continue
        note = "trend unchecked"
        if s in trend:
            close, ma20 = trend[s]
            if (side == "CE" and close < ma20) or (side == "PE" and close > ma20):
                continue  # build-up fights the 20-day trend
            note = f"{'above' if side == 'CE' else 'below'} 20-day avg ₹{ma20:,.0f}"
        chart = chart_check(candles[s], side, "daily") if s in candles else None
        if chart and chart["verdict"] in ("against", "weak"):
            continue  # the candles disagree with the build-up
        spot = float(f["UndrlygPric"])
        o = pick_option(fo, s, side, spot, day)
        if not o:
            continue
        lot, e = o["lot"], o["entry"]
        tgt, sl = e * (1 + CONFIG["target_pct"] / 100), e * (1 - CONFIG["stop_pct"] / 100)
        exp_label = datetime.strptime(o["expiry"], "%Y-%m-%d").strftime("%d %b")
        k, sign = o["strike"], 1 if side == "CE" else -1
        # what the option might be worth after 1 day if the stock moves, IV unchanged
        t1 = max(o["years"] - 1 / 365, 1 / 365)
        scen = []
        for m in (-3, -2, -1, 0, 1, 2, 3):
            px = bs_price(spot * (1 + m / 100), k, t1, o["iv"] / 100, side, R)
            scen.append({"move": m, "price": round(px, 2), "pct": round((px / e - 1) * 100, 1),
                         "pnl_lot": round((px - e) * lot - charges(e, px, lot))})
        need_move = (e * CONFIG["target_pct"] / 100) / max(abs(o["delta"]), 0.05)
        ma_txt = f" and {note}" if note != "trend unchecked" else ""
        why = [
            f"Futures {('rose' if f['price_chg'] > 0 else 'fell')} {abs(f['price_chg']):.2f}% while open interest "
            f"grew {f['oi_chg']:.1f}%: new {'buyers' if side == 'CE' else 'sellers'} are entering ({f['buildup'].lower()}).",
            f"{s} closed at ₹{spot:,.2f}{ma_txt}, so the move is with the trend, not against it.",
            f"Strike {k:g} is near the money (delta {o['delta']:+.2f}): it moves about ₹{abs(o['delta']):.2f} for each ₹1 in {s}.",
            f"Liquid: {o['volume']:,} contracts traded, open interest {o['oi']:,} shares, so you can get in and out.",
            f"{o['days']} days to expiry, so time decay is slower than for an expiry-week option.",
        ]
        picks.append({
            "why": why, "scenarios": scen, "chart": chart, "days": o["days"], "gamma": round(o["gamma"], 5),
            "vega_lot": o["vega_lot"], "opt_oi_chg": o["oi_chg"], "opt_chg": o["opt_chg"],
            "fut_oi": int(f["OpnIntrst"]), "breakeven": round(k + sign * e, 2),
            "max_loss_lot": round(e * lot), "need_move": round(need_move, 2),
            "need_move_pct": round(need_move / spot * 100, 2),
            "symbol": s, "side": side, "contract": f"{s} {exp_label} {o['strike']:g} {side}",
            "expiry": o["expiry"], "strike": o["strike"], "entry": e, "target": round(tgt, 2),
            "stop": round(sl, 2), "lot": lot, "cost_per_lot": round(e * lot),
            "profit_per_lot": round((tgt - e) * lot - charges(e, tgt, lot)),
            "loss_per_lot": round((sl - e) * lot - charges(e, sl, lot)),
            "delta": o["delta"], "theta_lot": o["theta_lot"], "iv": o["iv"], "oi": o["oi"],
            "volume": o["volume"], "spot": spot, "price_chg": round(float(f["price_chg"]), 2),
            "oi_chg": round(float(f["oi_chg"]), 1), "buildup": f["buildup"], "trend": note,
            "affordable": e * lot <= CONFIG["capital_per_trade"],
        })
        per_side[side] += 1
    return picks


# ---------------------------------------------------------------- long term
def long_term(day):
    members = index_members()
    if not members:
        return [], "index member lists unavailable", {}
    tick = {s: s + ".NS" for s, *_ in members}
    closes = yahoo_closes(list(tick.values()) + ["^NSEI"], "6y")
    closes = closes[closes.index.date <= day]

    def cagr(ser, years):
        start = ser.index[-1] - pd.DateOffset(years=years)
        if ser.index[0] > start + pd.Timedelta(days=7):
            return None  # not enough history (e.g. listed recently)
        sub = ser[ser.index <= start + pd.Timedelta(days=7)]
        if sub.empty:
            return None
        then = float(sub.iloc[-1])
        return round(((float(ser.iloc[-1]) / then) ** (1 / years) - 1) * 100, 1)

    def max_drawdown(ser):
        return round(float((ser / ser.cummax() - 1).min() * 100), 1)

    rows = []
    for s, name, idx, ind in members:
        ser = closes[tick[s]].dropna() if tick[s] in closes else pd.Series(dtype=float)
        if len(ser) < 260:
            continue
        p = float(ser.iloc[-1])
        ma50, ma200 = float(ser.tail(50).mean()), float(ser.tail(200).mean())
        y1 = ser.tail(252)
        hi52, lo52 = float(y1.max()), float(y1.min())
        vol = float(ser.pct_change().tail(252).std() * math.sqrt(252) * 100)
        weekly = ser.tail(260).iloc[::-5].iloc[::-1]  # weekly points ending on the latest close
        ser5 = ser[ser.index >= ser.index[-1] - pd.DateOffset(years=5)]
        rows.append({"symbol": s, "name": name, "index": idx, "industry": ind, "price": round(p, 2),
                     "ma50": round(ma50, 2), "ma200": round(ma200, 2), "high52": round(hi52, 2),
                     "low52": round(lo52, 2), "from_high": round((p / hi52 - 1) * 100, 1),
                     "ret6m": round((p / float(ser.iloc[-126]) - 1) * 100, 1),
                     "ret12m": round((p / float(ser.iloc[-252]) - 1) * 100, 1),
                     "cagr3": cagr(ser, 3), "cagr5": cagr(ser, 5),
                     "dd1y": max_drawdown(y1), "dd5y": max_drawdown(ser5),
                     "volatility": round(vol, 1),
                     "spark": [[d.strftime("%b %y"), round(float(v), 2)] for d, v in weekly.items()]})
    if not rows:
        return [], "price history unavailable", {}
    bench = {}
    if "^NSEI" in closes:
        n = closes["^NSEI"].dropna()
        if len(n) > 260:
            bench = {"ret12m": round((float(n.iloc[-1]) / float(n.iloc[-252]) - 1) * 100, 1),
                     "cagr3": cagr(n, 3), "cagr5": cagr(n, 5),
                     "dd5y": max_drawdown(n[n.index >= n.index[-1] - pd.DateOffset(years=5)])}
    df = pd.DataFrame(rows)
    ok = df[(df.price > df.ma200) & (df.ma50 > df.ma200) & (df.from_high >= -D["lt_max_from_high"]) & (df.ret12m > 0)].copy()
    z = lambda c: (ok[c] - ok[c].mean()) / (ok[c].std() or 1)
    ok["score"] = z("ret6m") + z("ret12m") - 0.5 * z("volatility")
    ok = ok.sort_values("score", ascending=False)
    # rank large and mid/small caps separately so fast-moving small caps can't crowd out steady large ones
    is_large = ok["index"] == "Large cap"
    ok = pd.concat([ok[is_large].head(D["lt_top_large"] * 2), ok[~is_large].head(D["lt_top_small"] * 2)])
    from analysis import chart_check, fundamentals
    sector_of = {s: ind for s, _n, _i, ind in members}
    health = fundamentals(ok["symbol"].tolist(), sector_of)
    ok["health"] = ok["symbol"].map(lambda s: (health.get(s) or {}).get("health"))
    ok = ok[ok["health"].isna() | (ok["health"] >= D["lt_min_health"])].copy()
    # final rank: half price momentum, half company health
    ok["score"] = ok["score"] + (ok["health"].fillna(55) - 60) / 15
    ok = ok.sort_values("score", ascending=False)
    is_large = ok["index"] == "Large cap"
    ok = pd.concat([ok[is_large].head(D["lt_top_large"]), ok[~is_large].head(D["lt_top_small"])])
    candles = yahoo_ohlc([s + ".NS" for s in ok["symbol"]], "6mo")
    out = []
    for r in ok.to_dict("records"):
        r = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()}  # NaN -> None
        ext = (r["price"] / r["ma50"] - 1) * 100
        r["extended"] = ext > D["lt_extended_pct"]
        r["zone"] = (f"Price jumped {ext:.0f}% above its usual level recently: wait for it to come down near ₹{r['ma50']:,.0f}"
                     if r["extended"] else f"Price is close to its usual level (₹{r['ma50']:,.0f}): a reasonable time to buy")
        r["score"] = round(r["score"], 2)
        hl = health.get(r["symbol"]) or {}
        r["fund"] = hl or None
        r["health"] = hl.get("health")
        for k in ("pe", "pb", "mcap_cr", "div_yield"):
            r[k] = hl.get(k)
        f = candles.get(r["symbol"] + ".NS")
        r["chart"] = chart_check(f[f.index.date <= day], "CE", "daily") if f is not None else None
        if r["chart"] and r["chart"]["rsi"] > 70:
            r["zone"] = f"Went up too fast recently: wait for a small dip, ideally near ₹{r['ma50']:,.0f}"
            r["extended"] = True
        out.append(r)

    # suggested split of the long-term budget: equal weight across up to 5 names,
    # preferring ones in a fair entry zone, max 2 per sector
    budget, chosen, sectors, small = D["lt_budget"], [], {}, 0
    for r in sorted(out, key=lambda x: (x["extended"], -x["score"])):
        if r["price"] > budget / 5:
            continue  # one share costs more than a fifth of the budget
        if r["volatility"] > D["lt_max_vol_for_split"]:
            continue  # too jumpy for a beginner's basket (still shown in the list)
        if r["index"] != "Large cap" and small >= D["lt_max_small"]:
            continue  # keep most of the money in large, steadier companies
        if len(chosen) < 5 and sectors.get(r["industry"], 0) < 2:
            small += r["index"] != "Large cap"
            chosen.append(r)
            sectors[r["industry"]] = sectors.get(r["industry"], 0) + 1
    each = budget / max(len(chosen), 1)
    for r in out:
        r["alloc_shares"] = int(each // r["price"]) if r in chosen else 0
        r["alloc_amount"] = round(r["alloc_shares"] * r["price"]) if r in chosen else 0
    note = f"{len(out)} of {len(df)} companies (NIFTY 500) are healthy and in a steady rise"
    return out, note, bench


# ------------------------------------------------------------------- run
def run():
    day, fo = latest_fo()
    log(f"daily: using NSE F&O file for {day}")
    grade_pending(day, fo)
    prev = read_json(OUT, {})
    if prev.get("date") == day.isoformat() and not D.get("rerun_same_day"):
        log("daily: already processed this file")
    banned = ban_list()
    picks = make_picks(fo, day, banned)
    try:
        lt, lt_note, bench = long_term(day)
    except Exception as e:
        log(f"daily: long-term failed {e!r}")
        lt, lt_note, bench = prev.get("long_term", []), "using previous list (refresh failed)", prev.get("benchmark", {})
    write_json(OUT, {"generated": now_ist().isoformat(timespec="seconds"), "date": day.isoformat(),
                     "options": picks, "banned": sorted(banned), "long_term": lt, "long_term_note": lt_note,
                     "benchmark": bench, "lt_budget": D["lt_budget"]})
    write_json(PENDING, {"date": day.isoformat(), "picks": picks})

    notify(*picks_message(picks, lt, day.isoformat()), level="signal")
    return True


def picks_message(picks, lt, day):
    """Evening message: option setups for the next session + long-term watchlist."""
    from datetime import date
    top = [p for p in picks if p["affordable"]][:4] or picks[:4]
    lines = [f"{'📈' if p['side'] == 'CE' else '📉'} {p['contract']} ~₹{p['entry']:.2f} "
             f"(lot {p['lot']}, ₹{p['cost_per_lot']:,}) → +₹{p['profit_per_lot']:,}/lot at target" for p in top]
    lt_line = ", ".join(r["symbol"] for r in lt[:5])
    url = CONFIG.get("dashboard_url")
    label = date.fromisoformat(day).strftime("%d %b") if day else ""
    return (f"Picks for next session (data {label})",
            ("\n".join(lines) or "No option setups passed the filters today.") +
            (f"\nLong-term watchlist: {lt_line}" if lt_line else "") +
            f"\nBuy only at the open if within {D['gap_skip_pct']}% of these prices. Paper-trade first." +
            (f"\n{url}" if url else ""))
