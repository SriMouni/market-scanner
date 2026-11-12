"""Send alerts to Mac pop-up, Telegram and WhatsApp.

level="status"  -> routine 15-min updates (noisy)  -> channels with "all"
level="signal"  -> buy / exit / daily summary       -> every enabled channel

WhatsApp providers (set in .env / GitHub secrets):
  CallMeBot (free, personal): WHATSAPP_PHONE=+91XXXXXXXXXX  CALLMEBOT_APIKEY=xxxx
  Twilio:  TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM=whatsapp:+14155238886, WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
"""
import subprocess
import sys

import requests

from common import CONFIG, env, log


def _wants(channel, level):
    mode = CONFIG["notify"].get(channel, "off")  # "all" | "signals" | "off"
    return mode == "all" or (mode == "signals" and level == "signal")


def _mac(title, body):
    if sys.platform != "darwin":
        return
    safe = lambda s: s.replace("\\", "").replace('"', "'")
    script = f'display notification "{safe(body)}" with title "{safe(title)}" sound name "Glass"'
    subprocess.run(["osascript", "-e", script], check=False)


def _telegram(text):
    """TELEGRAM_CHAT_ID may list several chats, comma-separated: your own chat id, a channel
    (@channelname or -100...), a group. Each gets the message; one failing doesn't stop the rest."""
    tok, chats = env("TELEGRAM_BOT_TOKEN"), [c.strip() for c in (env("TELEGRAM_CHAT_ID") or "").split(",") if c.strip()]
    if not (tok and chats):
        return "telegram not configured"
    errs = []
    for chat in chats:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat, "text": text, "disable_web_page_preview": "true"}, timeout=20)
        if not r.ok:
            errs.append(f"{chat[:6]}…: {r.status_code} {r.text[:120]}")
    return "; ".join(errs) or None


def _whatsapp(text):
    if env("TWILIO_SID"):
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{env('TWILIO_SID')}/Messages.json",
            auth=(env("TWILIO_SID"), env("TWILIO_TOKEN")),
            data={"From": env("TWILIO_FROM"), "To": env("WHATSAPP_TO"), "Body": text[:1500]},
            timeout=20)
        return None if r.ok else f"twilio {r.status_code}: {r.text[:150]}"
    phone, key = env("WHATSAPP_PHONE"), env("CALLMEBOT_APIKEY")
    if not (phone and key):
        return "whatsapp not configured"
    r = requests.get("https://api.callmebot.com/whatsapp.php",
                     params={"phone": phone, "text": text[:1500], "apikey": key}, timeout=30)
    return None if r.ok and "ERROR" not in r.text.upper()[:300] else f"callmebot {r.status_code}: {r.text[:150]}"


def notify(title, body, level="status"):
    log(f"NOTIFY[{level}] | {title} | {body}")
    text = f"{title}\n{body}"
    if _wants("mac", level):
        _mac(title, body)
    for name, fn in (("telegram", _telegram), ("whatsapp", _whatsapp)):
        if _wants(name, level):
            try:
                err = fn(text)
                if err and "not configured" not in err:
                    log(f"{name} failed: {err}")
            except Exception as e:
                log(f"{name} failed: {e!r}")


def test():
    """Send a test to every channel, report what happened."""
    results = {"mac": "sent" if sys.platform == "darwin" else "not a Mac"}
    if sys.platform == "darwin":
        _mac("Market scanner", "Test notification ✅")
    for name, fn in (("telegram", _telegram), ("whatsapp", _whatsapp)):
        try:
            results[name] = fn("Market scanner: test message ✅") or "sent"
        except Exception as e:
            results[name] = repr(e)
    for k, v in results.items():
        print(f"{k:<9}: {v}")
