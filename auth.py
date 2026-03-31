import pyotp
import requests
import time
import logging
from config import (
    ANGEL_CLIENT_ID, ANGEL_API_KEY,
    ANGEL_PASSWORD, ANGEL_TOTP_SECRET
)

logger = logging.getLogger(__name__)

BASE_URL = "https://apiconnect.angelone.in"

_jwt_token   = None
_feed_token  = None
_token_expiry = 0


def _get_totp() -> str:
    return pyotp.TOTP(ANGEL_TOTP_SECRET).now()


def get_token() -> tuple[str, str]:
    """Returns (jwt_token, feed_token). Refreshes if expired."""
    global _jwt_token, _feed_token, _token_expiry

    if _jwt_token and time.time() < _token_expiry - 300:
        return _jwt_token, _feed_token

    logger.info("Logging in to Angel One SmartAPI...")
    headers = {
        "Content-Type":      "application/json",
        "Accept":            "application/json",
        "X-UserType":        "USER",
        "X-SourceID":        "WEB",
        "X-ClientLocalIP":   "192.168.1.1",
        "X-ClientPublicIP":  "192.168.1.1",
        "X-MACAddress":      "00:00:00:00:00:00",
        "X-PrivateKey":      ANGEL_API_KEY,
    }
    body = {
        "clientcode": ANGEL_CLIENT_ID,
        "password":   ANGEL_PASSWORD,
        "totp":       _get_totp(),
    }

    resp = requests.post(
        f"{BASE_URL}/rest/auth/angelbroking/user/v1/loginByPassword",
        json=body,
        headers=headers,
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("status"):
        raise ValueError(f"Angel One login failed: {data.get('message')}")

    _jwt_token   = data["data"]["jwtToken"]
    _feed_token  = data["data"]["feedToken"]
    _token_expiry = time.time() + 82800  # ~23 hours
    logger.info("Angel One login successful.")
    return _jwt_token, _feed_token


def auth_headers() -> dict:
    jwt, _ = get_token()
    return {
        "Authorization": f"Bearer {jwt}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
        "X-UserType":    "USER",
        "X-SourceID":    "WEB",
        "X-PrivateKey":  ANGEL_API_KEY,
    }
