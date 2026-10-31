import json, os, re, sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from playwright.sync_api import sync_playwright

TARGET_URL = os.getenv("TARGET_URL", "https://egy.voxcinemas.com/showtimes?c=mall-of-egy&d=20261216")
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
STATE_FILE = Path("state/vox_snapshot.json")
TZ = ZoneInfo("Africa/Cairo")
TITLE_RE = re.compile(r"avengers\s*:\s*doomsday", re.I)

def fetch_sections():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="en-GB", timezone_id="Africa/Cairo")
        try:
            response = page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            if response and response.status >= 400:
                raise RuntimeError(f"VOX returned HTTP {response.status}")
            page.wait_for_timeout(3500)
            sections = page.evaluate(r"""() => {
              const match = s => /avengers\s*:\s*doomsday/i.test(s || "");
              const heads = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].filter(h => match(h.innerText));
              const out = [];
              for (const h of heads) {
                let node = h;
                for (let i = 0; i < 7 && node; i++, node = node.parentElement) {
                  const t = (node.innerText || "").trim();
                  if (t.length > 50 && t.length < 12000) { out.push(t); break; }
                }
              }
              return out;
            }""")
            if not sections:
                lines = [x.strip() for x in page.locator("body").inner_text().splitlines() if x.strip()]
                for i, line in enumerate(lines):
                    if TITLE_RE.search(line):
                        sections.append("\n".join(lines[i:i+100]))
            cleaned = []
            for section in sections:
                lines = [re.sub(r"\s+", " ", x).strip() for x in section.splitlines()]
                cleaned.append("\n".join(x for x in lines if x))
            return sorted(set(cleaned))
        finally:
            browser.close()

def telegram_send(message):
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": message[:3900], "disable_web_page_preview": True}, timeout=30)
    r.raise_for_status()
    if not r.json().get("ok"):
        raise RuntimeError(f"Telegram API error: {r.text}")

def main():
    sections = fetch_sections()
    current = json.dumps(sections, ensure_ascii=False, sort_keys=True)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    old = STATE_FILE.read_text(encoding="utf-8") if STATE_FILE.exists() else None
    STATE_FILE.write_text(current, encoding="utf-8")
    now = datetime.now(TZ).strftime("%d-%m-%Y %H:%M:%S")
    if old is None:
        telegram_send("✅ تم تفعيل مراقبة VOX بنجاح.\nAvengers: Doomsday | Mall of Egypt | 16 ديسمبر 2026\n"
                      f"أول فحص: {now}\nتم حفظ الحالة الحالية كخط أساس. أي تغيير لاحق سيصلك.")
        print("Baseline saved.")
    elif current != old:
        details = "\n\n────────────\n\n".join(sections) if sections else "لم تعد حفلات Avengers: Doomsday ظاهرة."
        telegram_send("🔔 تغيير جديد في VOX – Avengers: Doomsday\n"
            "📍 Mall of Egypt | 📅 16 December 2026\n"
            f"🕒 وقت الاكتشاف: {now}\n\n{details[:2800]}\n\nصفحة الحجز:\n{TARGET_URL}")
        print("Change detected; alert sent.")
    else:
        print(f"No change. Checked at {now}.")

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"Monitor failed: {exc}", file=sys.stderr)
        raise
