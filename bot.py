import asyncio
import json
import logging
import os
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
TARGET_URL = os.getenv(
    "TARGET_URL",
    "https://egy.voxcinemas.com/showtimes?c=mall-of-egypt&d=20261216",
)
STATE_FILE = Path(os.getenv("STATE_FILE", "/var/data/vox_state.json"))
TZ = ZoneInfo("Africa/Cairo")
TITLE_RE = re.compile(r"avengers\s*:\s*doomsday", re.I)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("vox-monitor")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Could not read state file; starting with a fresh state")
    return {"subscribers": [], "snapshot": None, "last_check": None, "last_error": None}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


async def fetch_movie_sections():
    """Read the public showtimes page and return the two Doomsday show blocks."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="en-GB", timezone_id="Africa/Cairo")
        try:
            response = await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            if response and response.status >= 400:
                raise RuntimeError(f"VOX returned HTTP {response.status}")
            await page.wait_for_timeout(3500)

            sections = await page.evaluate(r"""() => {
              const titleMatch = (s) => /avengers\s*:\s*doomsday/i.test(s || "");
              const heads = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")]
                .filter(h => titleMatch(h.innerText));
              const out = [];
              for (const h of heads) {
                let node = h;
                let chosen = null;
                for (let i = 0; i < 7 && node; i++, node = node.parentElement) {
                  const t = (node.innerText || "").trim();
                  if (/mall of egypt/i.test(t) && t.length > 80 && t.length < 12000) {
                    chosen = t;
                    break;
                  }
                }
                if (chosen) out.push(chosen);
              }
              return out;
            }""")

            # Fallback for a layout where the movie title is not represented by a heading.
            if not sections:
                body = await page.locator("body").inner_text()
                lines = [x.strip() for x in body.splitlines() if x.strip()]
                for i, line in enumerate(lines):
                    if TITLE_RE.search(line):
                        sections.append("\n".join(lines[i:i + 100]))

            # Normalize whitespace so cosmetic page changes do not trigger alerts.
            normalized = []
            for section in sections:
                lines = [re.sub(r"\s+", " ", x).strip() for x in section.splitlines()]
                lines = [x for x in lines if x]
                normalized.append("\n".join(lines))
            return sorted(set(normalized))
        finally:
            await browser.close()


def pretty_snapshot(sections):
    if not sections:
        return "لم يتم العثور على حفلات Avengers: Doomsday في صفحة المواعيد حاليًا."
    parts = []
    for section in sections:
        # Keep the useful booking details and omit excessively long page fragments.
        parts.append(section[:3500])
    return "\n\n────────────\n\n".join(parts)


async def send_to_subscribers(app: Application, text: str):
    state = load_state()
    for chat_id in state.get("subscribers", []):
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=text[:3900],
                disable_web_page_preview=True,
            )
        except Exception:
            log.exception("Could not send Telegram message to chat %s", chat_id)


async def run_check(app: Application, manual=False):
    state = load_state()
    try:
        sections = await fetch_movie_sections()
        current = json.dumps(sections, ensure_ascii=False, sort_keys=True)
        previous = state.get("snapshot")
        now = datetime.now(TZ).strftime("%d-%m-%Y %H:%M:%S")

        state["last_check"] = now
        state["last_error"] = None

        if previous is None:
            state["snapshot"] = current
            save_state(state)
            if manual:
                await send_to_subscribers(
                    app,
                    "✅ تم تشغيل مراقبة VOX بنجاح.\n"
                    f"آخر فحص: {now}\n\n{pretty_snapshot(sections)}",
                )
            else:
                log.info("Initial snapshot saved; no alert sent.")
            return

        if current != previous:
            old_sections = json.loads(previous)
            state["snapshot"] = current
            save_state(state)
            message = (
                "🔔 تغيير جديد في VOX – Avengers: Doomsday\n"
                "📍 Mall of Egypt | 📅 16 December 2026\n"
                f"🕒 وقت الاكتشاف: {now}\n\n"
                "البيانات الحالية من صفحة الحجز:\n"
                f"{pretty_snapshot(sections)}\n\n"
                f"صفحة الحجز:\n{TARGET_URL}"
            )
            await send_to_subscribers(app, message)
        elif manual:
            await send_to_subscribers(
                app,
                f"✅ لا يوجد تغيير جديد ظاهر في صفحة المواعيد.\nآخر فحص: {now}\n{TARGET_URL}",
            )
        save_state(state)
    except Exception as exc:
        log.exception("VOX check failed")
        state["last_error"] = str(exc)[:500]
        state["last_check"] = datetime.now(TZ).strftime("%d-%m-%Y %H:%M:%S")
        save_state(state)
        if manual:
            await send_to_subscribers(app, f"⚠️ فشل الفحص: {str(exc)[:800]}")


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = load_state()
    if chat_id not in state["subscribers"]:
        state["subscribers"].append(chat_id)
        save_state(state)
    await update.message.reply_text(
        "تم تفعيل التنبيهات ✅\n"
        "سأراقب Avengers: Doomsday في VOX Mall of Egypt ليوم 16 ديسمبر 2026 "
        "كل 5 دقائق.\n\n"
        "الأوامر:\n/status حالة البوت\n/check فحص الآن\n/stop إيقاف التنبيهات"
    )


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = load_state()
    state["subscribers"] = [x for x in state["subscribers"] if x != chat_id]
    save_state(state)
    await update.message.reply_text("تم إيقاف التنبيهات لهذا الحساب.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    await update.message.reply_text(
        "🟢 VOX Monitor\n"
        f"الفحص كل: {CHECK_INTERVAL // 60} دقائق\n"
        f"آخر فحص: {state.get('last_check') or 'لم يبدأ بعد'}\n"
        f"المشتركون: {len(state.get('subscribers', []))}\n"
        f"آخر خطأ: {state.get('last_error') or 'لا يوجد'}\n"
        f"الرابط: {TARGET_URL}"
    )


async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("بدأت الفحص الآن…")
    await run_check(context.application, manual=True)


async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    await run_check(context.application, manual=False)


async def post_init(app: Application):
    app.job_queue.run_repeating(
        scheduled_check,
        interval=CHECK_INTERVAL,
        first=10,
        name="vox-five-minute-monitor",
    )
    log.info("VOX monitor started; interval=%s seconds", CHECK_INTERVAL)


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    log.info("Telegram bot polling started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
