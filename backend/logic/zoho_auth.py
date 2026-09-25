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
_last_error: dict = {"message": None}


def get_last_error() -> str | None:
    return _last_error["message"]


def _env(name: str) -> str:
    """Read an env var, tolerating stray whitespace/quotes pasted into Railway."""
    return (os.getenv(name) or "").strip().strip('"').strip("'")


def _get_oauth_base() -> str:
    explicit = _env("ZOHO_ACCOUNTS_URL")
    if explicit:
        return explicit.rstrip("/")
    dc = _env("ZOHO_DC").lower() or "com"
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
    client_id = _env("ZOHO_CLIENT_ID")
    client_secret = _env("ZOHO_CLIENT_SECRET")
    refresh_token = _env("ZOHO_REFRESH_TOKEN")

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
            data = resp.json()

            if "access_token" not in data:
                _last_error["message"] = f"Token refresh failed ({resp.status_code}): {data.get('error', data)}"
                logger.error(_last_error["message"])
                return None
            _last_error["message"] = None

            _token_cache["access_token"] = data["access_token"]
            # expires_in is in seconds (typically 3600)
            _token_cache["expires_at"] = now + data.get("expires_in", 3600)
            logger.info("Zoho access token refreshed successfully")
            return _token_cache["access_token"]

        except (httpx.HTTPError, ValueError) as e:
            _last_error["message"] = f"HTTP error refreshing token: {e}"
            logger.error(_last_error["message"])
            return None


def is_configured() -> bool:
    """Check if all required OAuth env vars are present."""
    return all([
        _env("ZOHO_CLIENT_ID"),
        _env("ZOHO_CLIENT_SECRET"),
        _env("ZOHO_REFRESH_TOKEN"),
    ])
