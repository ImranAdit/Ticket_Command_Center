"""
Access control — only individually approved Google accounts may use the tool.

Approved accounts come from the Railway variable ALLOWED_EMAILS (comma, space or
newline separated). Any Google account can be listed; there is no domain rule.
OWNER_EMAILS (default imran@adit.com) is always allowed so the owner can't be
locked out.

Flow:
  POST /api/auth/google  {access_token}  -> verifies the token with Google, checks the
                                            allowlist, sets an HttpOnly session cookie
  GET  /api/auth/me                      -> current user, or 401
  POST /api/auth/logout                  -> clears the cookie

Every other /api/* route requires a valid session whose email is STILL on the list,
so removing someone from ALLOWED_EMAILS revokes access on the next request.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

COOKIE = "tcc_session"
SESSION_TTL = int(os.getenv("SESSION_HOURS", "12")) * 3600
PUBLIC_API = ("/api/auth/", "/api/health")


def _split(v: str) -> set[str]:
    return {e.strip().lower() for e in re.split(r"[,\s;]+", v or "") if e.strip()}


def allowed_emails() -> set[str]:
    return _split(os.getenv("ALLOWED_EMAILS", "")) | _split(os.getenv("OWNER_EMAILS", "imran@adit.com"))


def is_allowed(email: str) -> bool:
    return (email or "").strip().lower() in allowed_emails()


def _secret() -> bytes:
    s = os.getenv("SESSION_SECRET") or ("tcc:" + (os.getenv("ZOHO_CLIENT_SECRET") or "") + (os.getenv("ZOHO_REFRESH_TOKEN") or ""))
    return hashlib.sha256(s.encode()).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session(email: str, name: str | None) -> str:
    body = _b64(json.dumps({"e": email, "n": name or "", "x": int(time.time()) + SESSION_TTL}).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_session(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    try:
        data = json.loads(_unb64(body))
    except Exception:
        return None
    if data.get("x", 0) < time.time() or not is_allowed(data.get("e", "")):
        return None
    return {"email": data["e"], "name": data.get("n") or None}


async def require_session(request: Request, call_next):
    """HTTP middleware: guard every /api/* route except the public ones."""
    path = request.url.path
    if path.startswith("/api/") and not path.startswith(PUBLIC_API) and request.method != "OPTIONS":
        if not read_session(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "Not signed in or access not granted"}, status_code=401)
    return await call_next(request)


class GoogleLogin(BaseModel):
    access_token: str


@router.post("/google")
async def google_login(req: GoogleLogin, request: Request):
    async with httpx.AsyncClient(timeout=15) as client:
        info = await client.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": req.access_token})
        if info.status_code != 200:
            return JSONResponse({"detail": "Google sign-in could not be verified. Please try again."}, status_code=401)
        tok = info.json()
        # the token must have been issued to THIS app's Google client
        client_id = (os.getenv("GOOGLE_CLIENT_ID") or os.getenv("VITE_GOOGLE_CLIENT_ID") or "").strip()
        if client_id and client_id not in (tok.get("aud"), tok.get("azp")):
            return JSONResponse({"detail": "Google sign-in was issued for a different app."}, status_code=401)
        email = (tok.get("email") or "").strip().lower()
        if not email or str(tok.get("email_verified")).lower() != "true":
            return JSONResponse({"detail": "Your Google account email is not verified."}, status_code=401)
        name = None
        try:
            u = await client.get("https://www.googleapis.com/oauth2/v3/userinfo",
                                 headers={"Authorization": f"Bearer {req.access_token}"})
            if u.status_code == 200:
                name = u.json().get("name") or u.json().get("given_name")
        except Exception:
            pass

    if not is_allowed(email):
        logger.info(f"Access denied for {email} (not in ALLOWED_EMAILS)")
        return JSONResponse({"detail": f"{email} hasn't been approved for access yet. Ask the tool owner to grant access.",
                             "email": email}, status_code=403)

    resp = JSONResponse({"email": email, "name": name})
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, make_session(email, name), max_age=SESSION_TTL, httponly=True,
                    secure=secure, samesite="lax", path="/")
    return resp


@router.get("/me")
def me(request: Request):
    s = read_session(request.cookies.get(COOKIE))
    if not s:
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    return s


@router.post("/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp
