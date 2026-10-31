# VOX Avengers Doomsday Monitor

Telegram alert bot for the public VOX Mall of Egypt showtimes page for 16 Dec 2026.
It checks every 5 minutes by default and alerts subscribers when the visible
Avengers: Doomsday showtime block changes.

## What it detects
- New/removed showtime entries visible on the showtimes page
- Changes to hall names/types visible on the page
- Changes to the listed schedule block for both `Avengers: Doomsday` and
  `Avengers: Doomsday (Infinity Vision)`

## Important limitation
The public showtimes page does not expose a complete live seat map. This version
does **not** claim to detect individual seat availability changes inside the
booking flow. Seat-map monitoring needs a separate inspection of the booking
page/API and may be limited by session, anti-bot, or CAPTCHA controls. It does
not bypass those controls and does not book tickets automatically.

## Create the Telegram bot
1. Open https://t.me/BotFather in Telegram.
2. Send `/newbot`, follow the prompts, and copy the token.
3. Keep the token private. Do not paste it into public chats or commit it to Git.

## Deploy on Render
This project is a long-running Telegram polling worker and uses a persistent disk
for the baseline snapshot/subscriber list.

1. Create a GitHub repository and upload these project files.
2. In Render, choose **New + -> Background Worker** and connect the repository.
3. Choose **Docker** as the runtime.
4. Add environment variable `BOT_TOKEN` with the token from BotFather.
5. Add `CHECK_INTERVAL_SECONDS` = `300`.
6. Add a persistent disk mounted at `/var/data` (smallest available size is enough).
7. Deploy the worker and wait for the logs to show `Telegram bot polling started`.

Render plan availability/pricing can change; check the current dashboard before
creating an always-on Background Worker. Do not use a sleeping/free web service
for a 24/7 polling process.

## Activate Telegram notifications
1. Open your new bot using its `t.me/<bot_username>` link.
2. Press **Start** or send `/start`.
3. The bot stores your chat ID as a subscriber. No chat ID needs to be entered
   manually in Render.

## Commands
- `/start` — subscribe to alerts
- `/status` — show the last check and bot status
- `/check` — run an immediate check
- `/stop` — unsubscribe this Telegram chat

## Local test (optional)
Install Docker, then:
```bash
docker build -t vox-monitor .
docker run --rm -e BOT_TOKEN="YOUR_TOKEN" -v "$PWD/data:/var/data" vox-monitor
```

## Notes
- The first successful check saves a baseline and does not send a change alert.
- The bot then alerts only when the extracted showtime block changes.
- If VOX changes its page layout, the scraper may need adjustment.
- Respect VOX website terms and reasonable request frequency. The default interval
  is 5 minutes; do not reduce it without permission.
