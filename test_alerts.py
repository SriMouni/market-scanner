"""Send one sample of every "can be invested" message, built from today's real data, marked 🧪 TEST.

    python app.py test-alerts
"""
import alerts
import brief
from common import CONFIG, DATA, now_ist, read_json
from notify import notify

T = "🧪 TEST · "


def run():
    sent = []
    # 1. NIFTY breakout, using the latest saved option chain and today's opening range
    ch = read_json(DATA / "chain.json", {})
    st = (read_json(DATA / "engine_state.json", {}).get("status") or {})
    if ch.get("rows"):
        spot = ch["spot"]
        side = "PE" if st.get("close") and st.get("or_low") and st["close"] < st["or_low"] else "CE"
        row = min(ch["rows"], key=lambda r: abs(r["strike"] - ch["atm"]))
        p = {"side": side, "strike": row["strike"], "expiry": ch["expiry"], "limit": row[side]["ltp"],
             "spot_at_signal": spot, "lots": 1,
             "or_high": st.get("or_high", spot + 60), "or_low": st.get("or_low", spot - 60)}
        title, body = alerts.nifty_signal(p)
        notify(T + title, body, level="signal")
        sent.append("NIFTY breakout")

    # 2. strong stock movers from the latest live scan
    sl = read_json(DATA / "stocks_live.json", {})
    rows = [r for r in sl.get("signals", []) if r.get("chart") and r["chart"]["verdict"] in ("strong", "ok")][:3] \
        or sl.get("signals", [])[:3]
    if rows:
        title, body = alerts.stock_watch(rows)
        notify(T + title, body + f"\n(from the scan at {sl['time'][11:16]})", level="signal")
        sent.append(f"stock movers ({', '.join(r['symbol'] for r in rows)})")

    # 3. morning plan
    title, body = brief.build()
    notify(T + title, body, level="signal")
    sent.append("morning plan")

    # 4. evening picks for the next session
    d = read_json(DATA / "daily.json", {})
    if d.get("options") is not None:
        import daily
        title, body = daily.picks_message(d["options"], d.get("long_term", []), d.get("date", ""))
        notify(T + title, body, level="signal")
        sent.append("next-session picks")
    print(f"{now_ist():%H:%M} sent: " + "; ".join(sent))
