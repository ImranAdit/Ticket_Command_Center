"""
Extra Zoho queues shown on demand (not part of the SLA breach logic).

T2 CS - Open Unassigned
  Source : Zoho ticket view link in ZOHO_QUEUE_T2CS_UNASSIGNED
           (defaults to …/tickets/list/t2-cs-open-unassigned).
           NB: deliberately NOT a ZOHO_REPORT_* variable — those become breach departments.
  Viewers: QUEUE_VIEWERS (comma separated) + the owner. Everyone else gets 403.

GET /api/queue/t2cs-unassigned          rows for the dashboard (cached ~60s)
GET /api/queue/t2cs-unassigned?refresh=1  bypass the cache
GET /api/queue/t2cs-unassigned?debug=1  field names only (owner) — to map Deal Name / Created by
"""
import asyncio
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routers.auth import COOKIE, read_session, is_owner, can_view_queue
from services import zoho_fetcher_v2 as zf

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_LINK = "https://help.adit.com/agent/aditadvertising/support/tickets/list/t2-cs-open-unassigned"
KNOWN_DEPT_IDS = {"197800000000006907"}
CACHE_SECONDS = 60

_cache: dict = {"at": 0.0, "payload": None}
_detail_cache: dict[str, dict] = {}     # ticket id -> {"modified": ..., "detail": {...}}
_agent_names: dict[str, Optional[str]] = {}


def _session(request: Request) -> Optional[dict]:
    return read_session(request.cookies.get(COOKIE))


async def _find_view(client: httpx.AsyncClient, slug: str) -> Optional[dict]:
    dept_ids = set(KNOWN_DEPT_IDS)
    for ts in (zf.LAST_GROUPED_RAW or {}).values():
        for t in ts:
            if t.get("departmentId"):
                dept_ids.add(str(t["departmentId"]))
    for did in sorted(dept_ids) + ["allDepartment"]:
        data = await zf._get_with_retry(client, f"{zf._api_base()}/api/v1/views",
                                        params={"module": "tickets", "departmentId": did, "limit": 100})
        for v in (data or {}).get("data") or []:
            if zf._name_slug(v.get("name")) == slug:
                return v
    return None


async def _detail(client: httpx.AsyncClient, t: dict) -> dict:
    tid = str(t["id"])
    c = _detail_cache.get(tid)
    if c and c["modified"] == t.get("modifiedTime"):
        return c["detail"]
    d = await zf._get_with_retry(client, f"{zf._api_base()}/api/v1/tickets/{tid}",
                                 params={"include": "contacts,assignee,departments,team"}) or {}
    _detail_cache[tid] = {"modified": t.get("modifiedTime"), "detail": d}
    return d


async def _last_note(client: httpx.AsyncClient, t: dict, d: dict) -> Optional[str]:
    """Time of the most recent note (comment) on the ticket; cached with the ticket detail."""
    c = _detail_cache.get(str(t["id"])) or {}
    if "last_note" in c:
        return c["last_note"]
    last = None
    if d.get("commentCount") not in (0, "0"):
        j = await zf._get_with_retry(client, f"{zf._api_base()}/api/v1/tickets/{t['id']}/comments",
                                     params={"from": 0, "limit": 100})
        times = [x.get("commentedTime") for x in (j or {}).get("data") or [] if x.get("commentedTime")]
        last = max(times) if times else None
    if c:
        c["last_note"] = last
    return last


def _custom_fields(d: dict) -> dict:
    out = {}
    for key in ("cf", "customFields"):
        v = d.get(key)
        if isinstance(v, dict):
            out.update(v)
    return out


# Zoho fields that hold the deal, best first ("Deal Name" is a CRM lookup on most tickets)
DEAL_KEYS = ("Deal Name", "cf_deal_name", "Deal Names", "Deal", "cf_deal", "cf_related_deal")


def _text(v) -> Optional[str]:
    """Readable text from a Zoho field value (plain text, lookup object or list)."""
    if v is None:
        return None
    if isinstance(v, dict):
        for k in ("name", "displayName", "Deal_Name", "dealName", "value", "label"):
            if v.get(k):
                return str(v[k]).strip()
        return None
    if isinstance(v, list):
        parts = [p for p in (_text(x) for x in v) if p]
        return ", ".join(parts) or None
    s = str(v).strip()
    return None if s in ("", "{}", "[]", "null", "None") else s


def _clean_deals(s: str) -> str:
    """'Pittsburg Dental - PDS(1607…);Sky Dental - SKY(1607…)' -> 'Pittsburg Dental - PDS, Sky Dental - SKY'"""
    import re
    parts = [re.sub(r"\s*\(\d{6,}\)\s*$", "", p).strip() for p in s.split(";")]
    return ", ".join(p for p in parts if p)


def _deal_name(d: dict) -> Optional[str]:
    cf = _custom_fields(d)
    for k in DEAL_KEYS:
        t = _text(cf.get(k))
        if t:
            return _clean_deals(t)
    contact = d.get("contact") if isinstance(d.get("contact"), dict) else {}
    acc = d.get("account") if isinstance(d.get("account"), dict) else (contact.get("account") or {})
    return _text(acc.get("accountName") if isinstance(acc, dict) else None) or _text(d.get("accountName"))


async def _agent_name(client: httpx.AsyncClient, agent_id) -> Optional[str]:
    if not agent_id:
        return None
    aid = str(agent_id)
    if aid not in _agent_names:
        a = await zf._get_with_retry(client, f"{zf._api_base()}/api/v1/agents/{aid}", retries=1)
        _agent_names[aid] = (f"{(a or {}).get('firstName') or ''} {(a or {}).get('lastName') or ''}".strip()
                             or (a or {}).get("name") or None)
    return _agent_names[aid]


def _contact_name(d: dict) -> Optional[str]:
    c = d.get("contact") if isinstance(d.get("contact"), dict) else {}
    name = f"{c.get('firstName') or ''} {c.get('lastName') or ''}".strip()
    return name or c.get("email") or d.get("email") or None


async def _build() -> dict:
    url = os.getenv("ZOHO_QUEUE_T2CS_UNASSIGNED") or DEFAULT_LINK
    slug = zf._link_slug(url)
    if not slug:
        return {"error": "ZOHO_QUEUE_T2CS_UNASSIGNED must be a Zoho ticket view link (…/tickets/list/<view>)"}
    async with httpx.AsyncClient() as client:
        view = await _find_view(client, slug)
        if not view:
            return {"error": f"Zoho view '{slug}' not found"}
        tickets = await zf._fetch_view_tickets(client, str(view["id"]))
        if tickets is None:
            return {"error": f"Could not read the view: {zf._last_api_error}"}
        tickets = [t for t in tickets if (t.get("statusType") or "").lower() != "closed"]

        sem = asyncio.Semaphore(5)

        async def row(t: dict) -> dict:
            async with sem:
                d = await _detail(client, t)
                last_note = await _last_note(client, t, d)
            created_by = await _agent_name(client, d.get("createdBy")) or _contact_name(d)
            tid = str(t["id"])
            return {
                "id": tid,
                "ticketNumber": t.get("ticketNumber") or d.get("ticketNumber") or "",
                "subject": t.get("subject") or d.get("subject") or "No Subject",
                "deal_name": _deal_name(d),
                "priority": t.get("priority") or d.get("priority") or "None",
                "created_by": created_by,
                "created_time": t.get("createdTime") or d.get("createdTime"),
                "last_note_time": last_note,
                "status": t.get("status"),
                "zoho_url": t.get("webUrl") or d.get("webUrl") or
                f"https://help.adit.com/agent/aditadvertising/support/tickets/details/{tid}",
            }

        rows = await asyncio.gather(*(row(t) for t in tickets))
    rows.sort(key=lambda r: r.get("created_time") or "", reverse=True)
    return {"view": view.get("name"), "count": len(rows), "tickets": rows,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


@router.get("/t2cs-unassigned")
async def t2cs_unassigned(request: Request, refresh: bool = False, debug: bool = False):
    s = _session(request)
    if not s:
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    if not can_view_queue(s["email"]):
        return JSONResponse({"detail": "Not available for this account"}, status_code=403)

    if debug and is_owner(s["email"]):
        # structure only: which fields exist, so Deal Name / Created by can be mapped exactly
        async with httpx.AsyncClient() as client:
            view = await _find_view(client, zf._link_slug(os.getenv("ZOHO_QUEUE_T2CS_UNASSIGNED") or DEFAULT_LINK))
            if not view:
                return {"view": None}
            ts = await zf._fetch_view_tickets(client, str(view["id"])) or []
            d = await _detail(client, ts[0]) if ts else {}
            agent = await _agent_name(client, d.get("createdBy")) if d else None
        return {"view": view.get("name"), "count": len(ts),
                "list_keys": sorted(ts[0].keys()) if ts else [],
                "detail_keys": sorted(d.keys()), "custom_field_keys": sorted(_custom_fields(d).keys()),
                "has_createdBy": bool(d.get("createdBy")), "agent_lookup_ok": bool(agent),
                "contact_keys": sorted((d.get("contact") or {}).keys()) if isinstance(d.get("contact"), dict) else None,
                "deal_fields": {k: type(_custom_fields(d).get(k)).__name__ for k in DEAL_KEYS},
                "deal_name_resolved": _deal_name(d)}

    if refresh or not _cache["payload"] or time.time() - _cache["at"] > CACHE_SECONDS:
        try:
            payload = await _build()
        except Exception as e:
            logger.exception("[queue] build failed")
            payload = {"error": str(e)[:200]}
        if "error" not in payload:
            _cache.update(at=time.time(), payload=payload)
        elif _cache["payload"]:
            return {**_cache["payload"], "warning": payload["error"]}
        else:
            return JSONResponse(payload, status_code=502)
    return _cache["payload"]
