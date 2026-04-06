# OI Alert Bot — Troubleshooting Guide

## How the bot works (simple version)

Every hour during market hours (9:15 AM - 3:15 PM IST, Mon-Fri):
1. GitHub Actions wakes up
2. Authenticates with Groww API (token + secret)
3. Downloads instrument list to find expiry dates
4. Fetches live spot price for NIFTY and BANKNIFTY
5. Fetches full option chain (all strikes with OI)
6. Compares current OI with previous run's OI to calculate change
7. Sends formatted message to Telegram

---

## Common errors and fixes

### "Missing env vars: GROWW_API_TOKEN"
**Cause:** GitHub secret not set.
**Fix:** Go to your repo → Settings → Secrets and variables → Actions → New repository secret. Add the missing one.

Required secrets:
- `GROWW_API_TOKEN` — the long JWT token from Groww
- `GROW_API_SECRET` — the short secret string (note: one W, not two — matches .env)
- `TELEGRAM_BOT_TOKEN` — from BotFather (just the token, e.g. `8433362149:AAEeP7...`)
- `TELEGRAM_CHAT_ID` — your chat ID number

### "Groww auth failed" / "Groww token may have expired"
**Cause:** Your Groww API trial expired (45 days) or token was revoked.
**Fix:**
1. Log into Groww dashboard
2. Generate a new API token
3. Update `GROWW_API_TOKEN` in GitHub Secrets
4. If secret also changed, update `GROW_API_SECRET` too

### "Empty option chain" or "No strikes with OI"
**Cause:** Market holiday or expiry date mismatch.
**Fix:** Usually resolves itself next trading day. If persistent, the instrument CSV may have changed format — open an issue.

### "OI changes are all 0"
**Cause:** This is normal for:
- First run ever (no previous data to compare)
- Market closed (OI doesn't change when market is closed)
- Two runs within seconds (same data)
**Fix:** Wait for the next hourly run during market hours.

### Telegram message not received
**Cause:** Wrong bot token or chat ID.
**Fix:**
1. Message @BotFather on Telegram, send `/mybots`, click your bot — verify token
2. Message @userinfobot to verify your chat ID
3. Make sure you've started a conversation with your bot (send it /start)

### GitHub Actions not running
**Cause:** Cron schedule may be delayed (GitHub can delay up to 15 min) or workflow is disabled.
**Fix:**
1. Go to repo → Actions tab → check if workflow is enabled
2. You can always click "Run workflow" manually to test
3. GitHub cron can be delayed — this is normal

---

## How to test manually

### From your laptop:
```
cd oi-alert-bot
python groww_bot.py
```

### From GitHub:
1. Go to repo → Actions → "OI Alert Bot"
2. Click "Run workflow" → "Run workflow"
3. Watch the logs

---

## How to update the Groww token when it expires

1. Go to Groww API dashboard
2. Generate new token
3. GitHub repo → Settings → Secrets → Update `GROWW_API_TOKEN`
4. If secret changed too, update `GROW_API_SECRET`
5. Click "Run workflow" to test

---

## File structure

```
groww_bot.py          — the main bot (only file that matters)
requirements.txt      — Python packages
.env                  — local credentials (NOT pushed to GitHub)
.github/workflows/    — GitHub Actions schedule
state/                — OI snapshots (auto-managed, cached between runs)
```

---

## Adding more indices later

Edit `groww_bot.py`, find this line:
```python
for symbol in ["NIFTY", "BANKNIFTY"]:
```
Add more symbols, e.g.:
```python
for symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
```
