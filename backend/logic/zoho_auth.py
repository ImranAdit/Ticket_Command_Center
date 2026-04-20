"""
Zoho OAuth2 Token Manager
Handles access token refresh using stored refresh token.
Access tokens expire in 60 min — we refresh at 55 min.
"""
import os
import time
import logging
import httpx
from threading import Lock

logger = logging.getLogger(__name__)

_token_cache = {
    "access_token": None,
    "expires_at": 0,
}
_lock = Lock()


def _get_oauth_base() -> str:
    dc = os.getenv("ZOHO_DC", "com")
    mapping = {
        "com": "https://accounts.zoho.com",
        "eu": "https://accounts.zoho.eu",
        "in": "https://accounts.zoho.in",
        "au": "https://accounts.zoho.com.au",
        "jp": "https://accounts.zoho.jp",
    }
    return mapping.get(dc, "https://accounts.zoho.com")


def get_access_token() -> str | None:
    """Return a valid access token, refreshing if needed. Returns None if not configured."""
    client_id = os.getenv("ZOHO_CLIENT_ID")
    client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        logger.warning("Zoho OAuth credentials not configured in .env")
        return None

    with _lock:
        now = time.time()
        # Token still valid for > 60 seconds — return cached
        if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
            return _token_cache["access_token"]

        # Refresh the token
        url = f"{_get_oauth_base()}/oauth/v2/token"
        try:
            resp = httpx.post(url, data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if "access_token" not in data:
                logger.error(f"Token refresh failed: {data}")
                return None

            _token_cache["access_token"] = data["access_token"]
            # expires_in is in seconds (typically 3600)
            _token_cache["expires_at"] = now + data.get("expires_in", 3600)
            logger.info("Zoho access token refreshed successfully")
            return _token_cache["access_token"]

        except httpx.HTTPError as e:
            logger.error(f"HTTP error refreshing token: {e}")
            return None


def is_configured() -> bool:
    """Check if all required OAuth env vars are present."""
    return all([
        os.getenv("ZOHO_CLIENT_ID"),
        os.getenv("ZOHO_CLIENT_SECRET"),
        os.getenv("ZOHO_REFRESH_TOKEN"),
    ])
