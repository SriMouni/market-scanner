"""Shared helpers: config, time, logging, CSV, Black-Scholes, charges."""
import csv
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DOCS = BASE / "docs"
DATA.mkdir(exist_ok=True)
LOG_FILE = DATA / "scanner.log"
IST = timezone(timedelta(hours=5, minutes=30))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _load_env():
    """Read secrets from .env (local) - GitHub Actions passes them as real env vars."""
    f = BASE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
CONFIG = json.loads((BASE / "config.json").read_text())


def env(name, default=""):
    return os.environ.get(name, default).strip()


def now_ist():
    return datetime.now(IST)


def log(msg):
    line = f"{now_ist():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def append_csv(path, row):
    """Append a row; if the row has new columns, rewrite the file with the wider header first."""
    if path.exists():
        with path.open() as f:
            rd = csv.DictReader(f)
            header, old = list(rd.fieldnames or []), list(rd)
        extra = [k for k in row if k not in header]
        if extra:
            header += extra
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=header)
                w.writeheader()
                for r in old:
                    w.writerow({k: v for k, v in r.items() if k is not None})
        with path.open("a", newline="") as f:
            csv.DictWriter(f, fieldnames=header, extrasaction="ignore").writerow(row)
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerow(row)


def read_csv(path):
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=str))


# ------------------------------------------------------------ Black-Scholes
def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_price(spot, strike, years, sig, kind, r, q=0.0):
    st = sig * math.sqrt(years)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * sig * sig) * years) / st
    d2 = d1 - st
    if kind == "CE":
        return spot * math.exp(-q * years) * _ncdf(d1) - strike * math.exp(-r * years) * _ncdf(d2)
    return strike * math.exp(-r * years) * _ncdf(-d2) - spot * math.exp(-q * years) * _ncdf(-d1)


def implied_vol(price, spot, strike, years, kind, r, q=0.0):
    """IV in % from an option price (bisection). None if price is outside model range."""
    if price <= 0 or years <= 0:
        return None
    lo, hi = 0.01, 3.0
    if not (bs_price(spot, strike, years, lo, kind, r, q) <= price <= bs_price(spot, strike, years, hi, kind, r, q)):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs_price(spot, strike, years, mid, kind, r, q) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2 * 100


def greeks(spot, strike, years, iv_pct, kind, r, q=0.0):
    """delta, gamma, theta (₹/day per unit), vega (per 1% IV)."""
    sig = iv_pct / 100.0
    if sig <= 0 or years <= 0:
        return None
    st = sig * math.sqrt(years)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * sig * sig) * years) / st
    d2 = d1 - st
    dq, dr = math.exp(-q * years), math.exp(-r * years)
    gamma = dq * _npdf(d1) / (spot * st)
    vega = spot * dq * _npdf(d1) * math.sqrt(years) / 100
    common = -spot * dq * _npdf(d1) * sig / (2 * math.sqrt(years))
    if kind == "CE":
        delta = dq * _ncdf(d1)
        theta = common - r * strike * dr * _ncdf(d2) + q * spot * dq * _ncdf(d1)
    else:
        delta = -dq * _ncdf(-d1)
        theta = common + r * strike * dr * _ncdf(-d2) - q * spot * dq * _ncdf(-d1)
    return {"delta": delta, "gamma": gamma, "theta": theta / 365, "vega": vega}


def charges(entry, exit_, qty):
    """Estimated round-trip cost of buying then selling an option (₹)."""
    ch = CONFIG["charges"]
    buy_val, sell_val = entry * qty, exit_ * qty
    brokerage = 2 * ch["brokerage_per_order"]
    stt = sell_val * ch["stt_sell_pct"] / 100
    exch = (buy_val + sell_val) * ch["exchange_pct"] / 100
    sebi = (buy_val + sell_val) * 10 / 1e7
    stamp = buy_val * ch["stamp_buy_pct"] / 100
    gst = (brokerage + exch + sebi) * 0.18
    return brokerage + stt + exch + sebi + stamp + gst
