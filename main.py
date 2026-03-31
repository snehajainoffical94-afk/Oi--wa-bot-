"""
OI Alert Bot — Main entry point
Runs on APScheduler. No n8n needed.

Schedule:
  - Hourly OI update:  every 60 min, Mon-Fri, 9:15 AM – 3:30 PM IST
  - Spike check:       every 15 min, same window
"""

import logging
import time
from datetime import datetime
import pytz

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from fetcher import fetch_option_chain
from processor import process_chain
from formatter import format_update, format_spike_alert
from spike_detector import save_snapshot, detect_spikes
from notifier import send_telegram
from config import INDICES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    open_  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    close_ = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_ <= now <= close_


def run_oi_update():
    """Fetch OI for all indices and send formatted update."""
    if not is_market_open():
        logger.info("Market closed — skipping OI update.")
        return

    logger.info("=== Running OI Update ===")
    for symbol in INDICES:
        try:
            df        = fetch_option_chain(symbol)
            processed = process_chain(df, symbol)
            message   = format_update(processed)

            send_telegram(message)
            save_snapshot(symbol, processed)
            logger.info(f"{symbol} update sent.")
            time.sleep(2)  # avoid Telegram rate limit between messages

        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            send_telegram(f"⚠️ OI Bot error for {symbol}: {str(e)[:200]}")


def run_spike_check():
    """Check for OI spikes and alert if found."""
    if not is_market_open():
        return

    logger.info("=== Running Spike Check ===")
    for symbol in INDICES:
        try:
            df        = fetch_option_chain(symbol)
            processed = process_chain(df, symbol)
            spikes    = detect_spikes(symbol, processed)

            if spikes:
                alert = format_spike_alert(symbol, processed["spot"], spikes)
                send_telegram(alert)
                logger.info(f"Spike alert sent for {symbol}: {len(spikes)} spike(s)")

            save_snapshot(symbol, processed)

        except Exception as e:
            logger.error(f"Spike check error for {symbol}: {e}")


def run_manual():
    """One-time manual run — bypasses market hours check."""
    logger.info("Manual run triggered (market hours bypassed).")
    for symbol in INDICES:
        try:
            df        = fetch_option_chain(symbol)
            processed = process_chain(df, symbol)
            message   = format_update(processed)
            send_telegram(message)
            save_snapshot(symbol, processed)
            logger.info(f"{symbol} update sent.")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            send_telegram(f"⚠️ OI Bot error for {symbol}: {str(e)[:200]}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # python main.py test  — run once immediately for demo/debug
        run_manual()
    else:
        # Production scheduler
        scheduler = BlockingScheduler(timezone=IST)

        # Hourly OI update: every hour at :15, Mon–Fri, 9 AM–3 PM
        scheduler.add_job(
            run_oi_update,
            CronTrigger(
                day_of_week="mon-fri",
                hour="9-15",
                minute="15",
                timezone=IST
            ),
            id="oi_update",
            name="Hourly OI Update",
        )

        # Spike check: every 15 min, Mon–Fri, 9:15 AM–3:30 PM
        scheduler.add_job(
            run_spike_check,
            CronTrigger(
                day_of_week="mon-fri",
                hour="9-15",
                minute="15,30,45",
                timezone=IST
            ),
            id="spike_check",
            name="Spike Check",
        )

        logger.info("Scheduler started. Waiting for market hours...")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Bot stopped.")
