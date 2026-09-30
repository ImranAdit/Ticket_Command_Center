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
    """Full-access accounts: see every department (owner + ALLOWED_EMAILS)."""
    return _split(os.getenv("ALLOWED_EMAILS", "")) | _split(os.getenv("OWNER_EMAILS", "imran@adit.com"))


# Department-only accounts: they see just the departments listed for them.
# Override on Railway with DEPT_ACCESS, e.g.
#   T1 Tech: a@adit.com, b@adit.com; VoIP: c@adit.com; PA: d@adit.com
# (when DEPT_ACCESS is set it replaces this default list entirely)
DEFAULT_DEPT_ACCESS = {
    "T1 Tech": "sebastin.n@adit.com, ronnie@adit.com",
    "VoIP": "samantha.shine@adit.com",
    "T2 Core Tech": "kiara.smith@adit.com",
    "Adit Pay": "sebastin.n@adit.com, sandy.clark@adit.com",
    "PA": "peter@adit.com",
}


def dept_access() -> dict[str, set[str]]:
    raw = (os.getenv("DEPT_ACCESS") or "").strip()
    if not raw:
        return {d: _split(e) for d, e in DEFAULT_DEPT_ACCESS.items()}
    out: dict[str, set[str]] = {}
    for part in re.split(r"[;\n]+", raw):
        if ":" in part:
            dept, emails = part.split(":", 1)
            if dept.strip():
                out.setdefault(dept.strip(), set()).update(_split(emails))
    return out


def access_for(email: str) -> dict | None:
    """{"role": "admin", "depts": None} | {"role": "dept", "depts": [...]} | None (no access)."""
    e = (email or "").strip().lower()
    if not e:
        return None
    if e in allowed_emails():
        return {"role": "admin", "depts": None}
    depts = sorted(d for d, emails in dept_access().items() if e in emails)
    return {"role": "dept", "depts": depts} if depts else None


def is_allowed(email: str) -> bool:
    return access_for(email) is not None


def visible_depts(request: Request) -> set[str] | None:
    """Lower-cased department names this request may see; None = everything."""
    acc = getattr(request.state, "access", None)
    if not acc or acc.get("role") == "admin":
        return None
    return {d.lower() for d in acc.get("depts") or []}


def can_see_dept(request: Request, dept: str) -> bool:
    vis = visible_depts(request)
    return vis is None or (dept or "").lower() in vis


def can_act_on_ticket(request: Request, ticket_id: str) -> bool:
    if visible_depts(request) is None:
        return True
    from logic import cache
    return any(str(t.get("id")) == str(ticket_id)
               for d, ts in cache.get_all_cached_tickets().items() if can_see_dept(request, d)
               for t in ts)


# Department-only accounts may call just these API routes
DEPT_USER_PATHS = ("/api/sync/status", "/api/sync/tickets", "/api/sync/trigger",
                   "/api/actions/comment", "/api/actions/escalate")


def _secret() -> bytes:
    s = os.getenv("SESSION_SECRET") or ("tcc:" + (os.getenv("ZOHO_CLIENT_SECRET") or "") + (os.getenv("ZOHO_REFRESH_TOKEN") or ""))
    return hashlib.sha256(s.encode()).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session(email: str, name: str | None, picture: str | None = None) -> str:
    body = _b64(json.dumps({"e": email, "n": name or "", "p": picture or "",
                            "x": int(time.time()) + SESSION_TTL}).encode())
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
    return {"email": data["e"], "name": data.get("n") or None, "picture": data.get("p") or None,
            "super": is_owner(data["e"]), **access_for(data["e"])}


# ─── Who's online (super admin only) ──────────────────────────────────────
# In-memory: the dashboard calls the API at least once a minute, so anyone seen in the
# last ACTIVE_WINDOW seconds counts as active. Resets on redeploy (people reappear on
# their next poll).
ACTIVE_WINDOW = 180
_presence: dict[str, dict] = {}


def is_owner(email: str) -> bool:
    return (email or "").strip().lower() in _split(os.getenv("OWNER_EMAILS", "imran@adit.com"))


def touch_presence(s: dict) -> None:
    _presence[s["email"]] = {"email": s["email"], "name": s.get("name"), "picture": s.get("picture"),
                             "role": s.get("role"), "depts": s.get("depts"), "last_seen": time.time()}


async def require_session(request: Request, call_next):
    """HTTP middleware: guard every /api/* route except the public ones."""
    path = request.url.path
    if path.startswith("/api/") and not path.startswith(PUBLIC_API) and request.method != "OPTIONS":
        s = read_session(request.cookies.get(COOKIE))
        if not s:
            return JSONResponse({"detail": "Not signed in or access not granted"}, status_code=401)
        request.state.access = {"role": s["role"], "depts": s["depts"]}
        touch_presence(s)
        if s["role"] != "admin" and not path.startswith(DEPT_USER_PATHS):
            return JSONResponse({"detail": "Not available for department-level access"}, status_code=403)
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
        name, picture = None, None
        try:
            u = await client.get("https://www.googleapis.com/oauth2/v3/userinfo",
                                 headers={"Authorization": f"Bearer {req.access_token}"})
            if u.status_code == 200:
                name = u.json().get("name") or u.json().get("given_name")
                picture = u.json().get("picture")
        except Exception:
            pass

    if not is_allowed(email):
        logger.info(f"Access denied for {email} (not in ALLOWED_EMAILS)")
        return JSONResponse({"detail": f"{email} hasn't been approved for access yet. Ask the tool owner to grant access.",
                             "email": email}, status_code=403)

    token = make_session(email, name, picture)
    session = read_session(token)
    touch_presence(session)
    resp = JSONResponse(session)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True,
                    secure=secure, samesite="lax", path="/")
    return resp


@router.get("/me")
def me(request: Request):
    s = read_session(request.cookies.get(COOKIE))
    if not s:
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    touch_presence(s)
    return s


@router.get("/active")
def active_users(request: Request):
    """Who is signed in and active right now — visible to the super admin (owner) only."""
    s = read_session(request.cookies.get(COOKIE))
    if not s:
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    if not s.get("super"):
        return JSONResponse({"detail": "Super admin only"}, status_code=403)
    touch_presence(s)
    now = time.time()
    users = [
        {**u, "seconds_ago": int(now - u["last_seen"]), "you": u["email"] == s["email"]}
        for u in sorted(_presence.values(), key=lambda u: -u["last_seen"])
        if now - u["last_seen"] <= ACTIVE_WINDOW and is_allowed(u["email"])
    ]
    return {"window_seconds": ACTIVE_WINDOW, "users": users}


@router.post("/logout")
def logout(request: Request):
    s = read_session(request.cookies.get(COOKIE))
    if s:
        _presence.pop(s["email"], None)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp
