"""
SLA preview (rules v3) — runs alongside the existing dashboard.

After each main sync, takes the tickets already pulled for our departments, fetches the
per-ticket details the new rules need (history, threads, private notes, calendar
screenshots), evaluates logic/sla_rules.py and keeps the result in memory for
/api/sla/preview. Details are cached per ticket and only re-fetched when the
ticket's modifiedTime changes, to stay within Zoho API limits.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import io
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from logic import sla_rules
from logic.zoho_auth import get_access_token

logger = logging.getLogger(__name__)

CONCURRENCY = 4
HISTORY_PAGES = 4  # 4 x 50 events
# Zoho history property that records a change of assigned agent
OWNER_PROPERTIES = {"case owner", "ticket owner", "assignee", "owner"}
_details_cache: dict[str, dict] = {}      # ticket id -> {"modified": str, "details": {...}}
_ocr_cache: dict[str, Optional[str]] = {}  # image url -> text
_state: dict = {
    "running": False,
    "generated_at": None,
    "progress": {"done": 0, "total": 0},
    "errors": [],
    "departments": {},
    "counts": {},
}


def get_state() -> dict:
    return _state


# ─── Zoho helpers ─────────────────────────────────────────────────────────────

def _api_base() -> str:
    from services.zoho_fetcher_v2 import _api_base as base
    return base()


def _headers() -> dict:
    from services.zoho_fetcher_v2 import _headers as h
    return h()


async def _get(client: httpx.AsyncClient, path: str, params: Optional[dict] = None) -> Optional[dict]:
    url = path if path.startswith("http") else f"{_api_base()}{path}"
    delay = 2
    for attempt in range(3):
        try:
            resp = await client.get(url, params=params, headers=_headers(), timeout=25)
            if resp.status_code == 429:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 204 or not resp.content:
                return {"data": []}
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            _note_error(f"{path}: {e.response.status_code} {e.response.text[:150]}")
            return None
        except Exception as e:  # network / JSON
            if attempt == 2:
                _note_error(f"{path}: {e}")
                return None
            await asyncio.sleep(delay)
            delay *= 2
    return None


def _note_error(msg: str) -> None:
    logger.warning(f"[sla] {msg}")
    errs = _state["errors"]
    if msg not in errs:
        errs.append(msg)
        del errs[:-20]


def _val_name(v) -> str:
    if isinstance(v, dict):
        return str(v.get("name") or v.get("displayName") or v.get("value") or v.get("id") or "")
    return str(v or "")


def _is_agent(person: Optional[dict]) -> bool:
    if not isinstance(person, dict):
        return True  # Zoho omits author on some agent actions
    t = str(person.get("type") or "").upper()
    return t not in ("END_USER", "ENDUSER", "CONTACT", "CUSTOMER")


def _html_to_text(content: str) -> str:
    t = re.sub(r"<br\s*/?>|</p>|</div>", "\n", content or "", flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return html_lib.unescape(t)


def _image_urls(comment: dict) -> list[str]:
    urls = re.findall(r'<img[^>]+src="([^"]+)"', comment.get("content") or "", flags=re.I)
    for a in comment.get("attachments") or []:
        name = str(a.get("name") or "").lower()
        href = a.get("href") or a.get("url")
        if href and name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
            urls.append(href)
    out = []
    for u in urls:
        u = html_lib.unescape(u)
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = _api_base() + u
        if u.startswith("http") and u not in out:
            out.append(u)
    return out


async def _ocr_image(client: httpx.AsyncClient, url: str) -> Optional[str]:
    if url in _ocr_cache:
        return _ocr_cache[url]
    text = None
    try:
        import pytesseract
        from PIL import Image
        headers = _headers() if "zoho" in url else {}
        resp = await client.get(url, headers=headers, timeout=30, follow_redirects=True)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
            img = Image.open(io.BytesIO(resp.content)).convert("L")
            if img.width < 1200:  # upscale small screenshots for better OCR
                img = img.resize((img.width * 2, img.height * 2))
            text = await asyncio.to_thread(pytesseract.image_to_string, img)
        else:
            _note_error(f"image download {resp.status_code} ({resp.headers.get('content-type', '')})")
    except ImportError:
        _note_error("OCR not available (pytesseract/tesseract missing)")
    except Exception as e:
        _note_error(f"OCR failed: {e}")
    _ocr_cache[url] = text
    return text


# ─── Per-ticket details ───────────────────────────────────────────────────────

async def _fetch_details(client: httpx.AsyncClient, ticket: dict) -> dict:
    tid = ticket["id"]
    status = (ticket.get("status") or "").strip().lower()
    threads_j, comments_j = await asyncio.gather(
        _get(client, f"/api/v1/tickets/{tid}/threads", {"from": 0, "limit": 100}),
        _get(client, f"/api/v1/tickets/{tid}/comments", {"from": 0, "limit": 100}),
    )

    agent_replies, customer_msgs, first_in = [], [], None
    threads = (threads_j or {}).get("data") or []
    dated = sorted(((sla_rules.parse_dt(t.get("createdTime")), t) for t in threads),
                   key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc))
    for i, (dt, th) in enumerate(dated):
        direction = str(th.get("direction") or "").lower()
        if i == 0 and dt:
            first_in = direction == "in"
        if not dt:
            continue
        if direction == "out" and _is_agent(th.get("author")):
            agent_replies.append(dt)
        elif direction == "in":
            customer_msgs.append(dt)

    notes = []
    for c in (comments_j or {}).get("data") or []:
        dt = sla_rules.parse_dt(c.get("commentedTime") or c.get("createdTime"))
        if not dt or not _is_agent(c.get("commenter")):
            continue
        notes.append({"time": dt, "text": _html_to_text(c.get("content") or ""),
                      "image_urls": _image_urls(c), "image_text": None})

    # OCR only where it matters: Pending Meeting notes that have no readable time in text
    if status in sla_rules.MEETING_STATUSES:
        for n in sorted(notes, key=lambda n: n["time"], reverse=True)[:3]:
            if sla_rules.parse_callback_time(n["text"], n["time"]):
                break
            for url in n["image_urls"][:2]:
                txt = await _ocr_image(client, url)
                if txt and sla_rules.parse_callback_time(txt, n["time"]):
                    n["image_text"] = txt
                    break
            if n["image_text"]:
                break

    # History is newest-first, max 50 per page and full of automation noise, so page
    # through (up to HISTORY_PAGES) until the latest owner change has been seen.
    assigned_at = resumed_at = None
    history_count = 0
    for page in range(HISTORY_PAGES):
        history_j = await _get(client, f"/api/v1/tickets/{tid}/History", {"from": page * 50, "limit": 50})
        events = (history_j or {}).get("data") or []
        history_count += len(events)
        for ev in events:
            et = sla_rules.parse_dt(ev.get("eventTime"))
            if not et:
                continue
            for info in ev.get("eventInfo") or []:
                prop = str(info.get("propertyName") or "").strip().lower()
                pv = info.get("propertyValue") or {}
                prev = _val_name(pv.get("previousValue")).lower() if isinstance(pv, dict) else ""
                if prop in OWNER_PROPERTIES:
                    assigned_at = max(assigned_at, et) if assigned_at else et
                if prop == "status" and prev in sla_rules.PAUSED_STATUSES:
                    resumed_at = max(resumed_at, et) if resumed_at else et
        if assigned_at or len(events) < 50:
            break

    return {
        "agent_replies": agent_replies,
        "customer_msgs": customer_msgs,
        "first_thread_in": first_in if threads else None,
        "notes": notes,
        "assigned_at": assigned_at,
        "resumed_at": resumed_at,
        "_counts": {"threads": len(threads), "notes": len(notes), "history": history_count},
    }


# ─── Main refresh ─────────────────────────────────────────────────────────────

async def refresh(grouped_raw: dict[str, list[dict]]) -> None:
    """grouped_raw: {department name: [raw Zoho ticket, ...]} from the main sync."""
    if _state["running"]:
        return
    if not get_access_token():
        _note_error("No Zoho access token")
        return
    _state["running"] = True
    _state["errors"] = []
    try:
        pairs = [(dept, t) for dept, ts in grouped_raw.items() for t in ts if t.get("id")]
        _state["progress"] = {"done": 0, "total": len(pairs)}
        sem = asyncio.Semaphore(CONCURRENCY)
        now = datetime.now(timezone.utc)
        out: dict[str, list[dict]] = {d: [] for d in grouped_raw}

        async with httpx.AsyncClient() as client:
            async def work(dept: str, t: dict):
                async with sem:
                    tid = str(t["id"])
                    cached = _details_cache.get(tid)
                    if cached and cached["modified"] == t.get("modifiedTime"):
                        details = cached["details"]
                    else:
                        details = await _fetch_details(client, t)
                        _details_cache[tid] = {"modified": t.get("modifiedTime"), "details": details}
                    ev = sla_rules.evaluate_ticket(t, details, now)
                    assignee = t.get("assignee") or {}
                    out[dept].append({
                        "id": tid,
                        "ticketNumber": t.get("ticketNumber"),
                        "subject": t.get("subject"),
                        "status": t.get("status"),
                        "agent": (f"{assignee.get('firstName', '')} {assignee.get('lastName', '')}".strip()
                                  or "Unassigned"),
                        "team": ((t.get("team") or {}).get("name")),
                        "assigneeId": t.get("assigneeId"),
                        "priority": t.get("priority") or "Normal",
                        "created_time": t.get("createdTime"),
                        "modified_time": t.get("modifiedTime"),
                        "due_date": t.get("dueDate"),
                        "zoho_url": t.get("webUrl") or
                        f"https://help.adit.com/agent/aditadvertising/support/tickets/details/{tid}",
                        **ev,
                    })
                    _state["progress"]["done"] += 1

            await asyncio.gather(*(work(d, t) for d, t in pairs))

        order = {"breach": 0, "at_risk": 1, "unclear": 2, "scheduled": 3, "ok": 4, "paused": 5}
        counts = {}
        for dept, rows in out.items():
            rows.sort(key=lambda r: (order.get(r["state"], 9), -r["hours"]))
            c = {}
            for r in rows:
                c[r["state"]] = c.get(r["state"], 0) + 1
            counts[dept] = c
        # drop stale cache entries
        live = {str(t.get("id")) for _, t in pairs}
        for k in list(_details_cache):
            if k not in live:
                _details_cache.pop(k, None)
        _state["departments"] = out
        _state["counts"] = counts
        _state["generated_at"] = now.isoformat()
        _publish_to_dashboard(out)
        logger.info(f"[sla] preview refreshed: {counts}")
    except Exception as e:
        logger.exception("[sla] preview refresh failed")
        _note_error(f"refresh failed: {e}")
    finally:
        _state["running"] = False


SEVERITY = {"breach": "critical", "at_risk": "moderate", "unclear": "watch"}


def _publish_to_dashboard(out: dict[str, list[dict]]) -> None:
    """Feed the main dashboard (/api/sync/tickets) with v3 results in its existing shape."""
    from services import zoho_fetcher_v2
    if not getattr(zoho_fetcher_v2, "V3_DASHBOARD", False):
        return
    from logic import cache
    for dept, rows in out.items():
        mapped = [{
            "id": r["id"],
            "ticketNumber": r.get("ticketNumber") or "",
            "subject": r.get("subject") or "No Subject",
            "status": r.get("status") or "",
            "assignee": r.get("agent") or "Unassigned",
            "assigneeId": r.get("assigneeId"),
            "priority": r.get("priority") or "Normal",
            "department": dept,
            "sla_status": "breached" if r["state"] == "breach" else "at_risk",
            "created_time": r.get("created_time"),
            "modified_time": r.get("modified_time"),
            "due_date": r.get("due_date"),
            "hours_overdue": r.get("hours") or 0,
            "severity": SEVERITY[r["state"]],
            "zoho_url": r.get("zoho_url"),
            "rule": r.get("rule"),
            "detail": r.get("detail"),
        } for r in rows if r["state"] in SEVERITY]
        cache.set_cached_tickets(dept, mapped)
        cache.set_dept_count(dept, sum(1 for m in mapped if m["severity"] == "critical"))


async def inspect(ticket_id: str) -> dict:
    """Structure-only view of one ticket's detail payloads (keys, event/property names) for debugging."""
    async with httpx.AsyncClient() as client:
        th = await _get(client, f"/api/v1/tickets/{ticket_id}/threads", {"from": 0, "limit": 5})
        co = await _get(client, f"/api/v1/tickets/{ticket_id}/comments", {"from": 0, "limit": 5})
        hi = await _get(client, f"/api/v1/tickets/{ticket_id}/History", {"from": 0, "limit": 20})

    def keys(j):
        d = (j or {}).get("data") or []
        return sorted({k for x in d for k in x.keys()}) if d else (j if j is None else [])

    return {
        "threads_keys": keys(th),
        "thread_samples": [{"direction": x.get("direction"), "authorType": (x.get("author") or {}).get("type"),
                            "createdTime": x.get("createdTime"), "channel": x.get("channel")}
                           for x in ((th or {}).get("data") or [])[:5]],
        "comments_keys": keys(co),
        "comment_samples": [{"isPublic": x.get("isPublic"), "commenterType": (x.get("commenter") or {}).get("type"),
                             "time": x.get("commentedTime"), "contentType": x.get("contentType"),
                             "images": len(_image_urls(x)), "attachments": len(x.get("attachments") or [])}
                            for x in ((co or {}).get("data") or [])[:5]],
        "history_keys": keys(hi),
        "history_events": [{"eventName": x.get("eventName"), "time": x.get("eventTime"),
                            "props": [i.get("propertyName") for i in (x.get("eventInfo") or [])]}
                           for x in ((hi or {}).get("data") or [])[:20]],
        "errors": _state["errors"][-5:],
    }
