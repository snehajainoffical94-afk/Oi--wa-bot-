import os
from dotenv import load_dotenv

load_dotenv()

# Angel One SmartAPI
ANGEL_CLIENT_ID   = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_API_KEY     = os.getenv("ANGEL_API_KEY", "")
ANGEL_API_SECRET  = os.getenv("ANGEL_API_SECRET", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")
ANGEL_PASSWORD    = os.getenv("ANGEL_PASSWORD", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# Bot settings
STRIKE_WINDOW    = int(os.getenv("STRIKE_WINDOW", "15"))
TOP_WALLS        = int(os.getenv("TOP_WALLS", "3"))
SPIKE_THRESHOLD  = int(os.getenv("SPIKE_THRESHOLD", "30"))
INDICES          = os.getenv("INDICES", "NIFTY,BANKNIFTY").split(",")
