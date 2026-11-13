"""Plain-language "this can be invested" messages. Built here so the live jobs and
`python app.py test-alerts` use exactly the same wording."""
from common import CONFIG


def _rs(x):
    sign, x = ("−" if x < 0 else ""), abs(x)
    return sign + (f"₹{x:,.2f}" if x < 100 else f"₹{x:,.0f}")


def _px(x):
    return f"₹{x:,.2f}"


def nifty_signal(p):
    """NIFTY broke out of its first-15-min range: buy now."""
    lot = CONFIG["intraday"]["lot_size"] * p.get("lots", 1)
    up = p["side"] == "CE"
    tgt = p["limit"] * (1 + CONFIG["target_pct"] / 100)
    stop = p["limit"] * (1 - CONFIG["stop_pct"] / 100)
    title = f"{'📈' if up else '📉'} NIFTY {'UP' if up else 'DOWN'}: buy {p['strike']:g} {p['side']} now"
    why = p.get("why") or (f"NIFTY closed {'above' if up else 'below'} today's opening range "
                           f"{p['or_low']:,.0f}–{p['or_high']:,.0f}")
    body = (f"Setup: {p.get('strategy') or 'Opening-range breakout'}\n{why} (now {p['spot_at_signal']:,.0f}).\n"
            f"Buy 1 lot ({lot} qty) NIFTY {p['expiry']} {p['strike']:g} {p['side']} with a LIMIT order "
            f"at up to {_px(p['limit'])} (≈{_rs(p['limit'] * lot)}).\n"
            f"Sell at {_px(tgt)} (+{CONFIG['target_pct']}% ≈ +{_rs((tgt - p['limit']) * lot)}) "
            f"or stop at {_px(stop)} (−{_rs((p['limit'] - stop) * lot)}). "
            f"Sell by {CONFIG['engine']['exit_by']} whatever happens.\n"
            f"If the price is already above {_px(p['limit'])}, skip it: don't chase."
            + _record(p.get("strategy") or "Opening-range breakout"))
    return title, body


def _record(name):
    """This setup's practice track record, so every alert says honestly how it has done."""
    try:
        import engine
        r = (engine.metrics().get("by_strategy") or {}).get(name)
    except Exception:
        r = None
    if not r or r["n"] < 1:
        return f"\n🧪 Track record: new setup, no completed practice trades yet."
    sign = "+" if r["exp"] >= 0 else "−"
    note = " (too few to judge)" if r["n"] < 30 else ""
    return f"\n🧪 Track record: {r['n']} practice trades, avg {sign}₹{abs(r['exp']):,}/trade{note}."


def stock_watch(rows):
    """New strong stock movers that were not practice-traded (limits already used)."""
    up = sum(r["signal"] == "CE" for r in rows)
    title = f"🔎 {len(rows)} stock{'s' if len(rows) > 1 else ''} moving strongly now"
    lines = []
    for r in rows:
        c, o = r.get("cash"), r.get("option")
        s = (f"{'📈' if r['signal'] == 'CE' else '📉'} {r['symbol']} ({r['sector']}) {r['chg']:+.1f}% "
             f"at {_rs(r['price'])}, volume {r['rvol']:.1f}x, chart {r['chart']['verdict'] if r.get('chart') else '–'}")
        if c:
            s += (f"\n   Shares: {c['action']} {c['qty']} → target {_rs(c['target'])} (+{_rs(c['profit'])}), "
                  f"stop {_rs(c['stop'])} ({_rs(c['loss'])})")
        if o and r.get("affordable"):
            s += f"\n   Option: {r['contract']} ~{_rs(o['est'])} (1 lot ≈ {_rs(o['cost_lot'])})"
        lines.append(s)
    exit_by = CONFIG["intraday"]["exit_all_by"]
    body = "\n".join(lines) + f"\nIntraday only, sell by {exit_by}." + (
        "" if up == len(rows) else " 📉 = price falling: buy PE / short-sell only if you know how.")
    url = CONFIG.get("dashboard_url")
    return title, body + (f"\nDetails: {url}" if url else "")
