"""Morning "what to buy today" message (sent once a day ~9:35 AM by the monitor job).

    python app.py brief            print it
    python app.py brief --send     send it to Mac / Telegram / WhatsApp
"""
from common import CONFIG, DATA, now_ist, read_json
from notify import notify


def _inr(x):
    sign = "−" if x < 0 else ""
    x = abs(x)
    return sign + (f"₹{x:,.0f}" if x >= 100 else f"₹{x:,.2f}")


def build():
    now = now_ist()
    d = read_json(DATA / "daily.json", {})
    es = read_json(DATA / "engine_state.json", {})
    sl = read_json(DATA / "stocks_live.json", {})
    status = (es.get("status") or {}) if es.get("day") == now.date().isoformat() else {}
    gap = CONFIG["daily"]["gap_skip_pct"]
    lines = [f"Plan for {now:%a %d %b} (practice mode: track it before using real money)"]

    # 1. NIFTY plan
    if status.get("or_high"):
        E = CONFIG["engine"]
        lines.append(f"\n📊 NIFTY: first 15 min range {status['or_low']:,.0f}–{status['or_high']:,.0f}.\n"
                     f"• Close ABOVE {status['or_high']:,.0f} → 'buy CE' · BELOW {status['or_low']:,.0f} → 'buy PE'\n"
                     f"• Also watching: trend pullbacks, failed breakouts and bounces off support/resistance\n"
                     f"Up to {E['max_trades_per_day']} trades today, one at a time, new buys until "
                     f"{E['entry_end']}. Wait for the 'buy now' message.")
    else:
        lines.append("\n📊 NIFTY: waiting for the first 15 minutes to set today's range. We'll message if it breaks out.")

    # 2. options idea (last night's scan, affordable, chart OK) - only when stock alerts are on
    stocks_on = CONFIG["stocks"].get("notify", True)
    opts = [p for p in d.get("options", []) if p.get("affordable")] if stocks_on else []
    if not stocks_on:
        pass
    elif opts:
        p = opts[0]
        lo, hi = p["entry"] * (1 - gap / 100), p["entry"] * (1 + gap / 100)
        lines.append(f"\n⚡ Option idea: BUY 1 lot {p['contract']} ({p['lot']} qty) only between {_inr(lo)}–{_inr(hi)}. "
                     f"Pay ~{_inr(p['cost_per_lot'])} · if it works +{_inr(p['profit_per_lot'])} · if not {_inr(p['loss_per_lot'])}. "
                     f"Sell by 3:15 PM.")
    else:
        lines.append("\n⚡ Option idea: none passed the checks today. That's fine: no trade beats a bad trade.")

    # 3. shares idea: live signal if any, else last night's strongest stock
    live = [r for r in sl.get("signals", []) if r.get("cash") and r["signal"] == "CE"] if \
        (stocks_on and (sl.get("time") or "").startswith(now.date().isoformat())) else []
    if live:
        r, c = live[0], live[0]["cash"]
        lines.append(f"\n🛒 Shares idea: BUY {c['qty']} {r['symbol']} at ~{_inr(c['entry'])} (intraday). "
                     f"Sell at {_inr(c['target'])} (+{_inr(c['profit'])}) or stop {_inr(c['stop'])} ({_inr(c['loss'])}).")
    elif opts and stocks_on:
        p = opts[0]
        qty = int(CONFIG["capital_per_trade"] // p["spot"])
        t, sp = CONFIG["stocks"]["cash_target_pct"], CONFIG["stocks"]["cash_stop_pct"]
        lines.append(f"\n🛒 Shares idea: {p['symbol']} closed at {_inr(p['spot'])}. If it's still rising after 9:45, "
                     f"buy ~{qty} shares intraday; sell at +{t}% or stop at −{sp}%. We'll message if the live scan confirms.")

    # 4. long term: fairly priced, healthy
    lt = [r for r in d.get("long_term", []) if not r.get("extended") and r.get("alloc_shares")]
    if lt:
        picks = ", ".join(f"{r['symbol']} ({r['alloc_shares']} sh ≈ {_inr(r['alloc_amount'])}, health {r.get('health') or '–'})" for r in lt[:3])
        lines.append(f"\n🌱 Long-term (hold 3+ yrs, buy with 'Delivery'): {picks}. Or simply a NIFTY 50 index fund.")

    url = CONFIG.get("dashboard_url")
    if url:
        lines.append(f"\nDetails & steps: {url}")
    return "☀️ What to buy today", "\n".join(lines)


def send():
    title, body = build()
    notify(title, body, level="signal")
    return title, body
