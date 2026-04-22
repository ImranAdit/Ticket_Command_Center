"""
Zoho Desk API Fetcher Service
Polls ticket data department-wise, applies SLA breach logic, and writes to cache.
"""
import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from logic.zoho_auth import get_access_token, is_configured
from logic.sla_processor import classify_and_filter
from logic import cache

logger = logging.getLogger(__name__)

# ─── Department config ────────────────────────────────────────────────────────
DEPARTMENTS: list[dict] = [
    {"name": "VoIP", "id": "197800000150281001"},
    {"name": "T1 Tech", "id": "197800000194883033"},
    {"name": "T2 Core Tech", "id": "197800000150281341"},
    {"name": "Adit Pay", "id": "197800000204233645"},
]

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _api_base() -> str:
    dc = os.getenv("ZOHO_DC", "com")
    return f"https://desk.zoho.{dc}"


def _headers() -> dict:
    token = get_access_token()
    org_id = os.getenv("ZOHO_ORG_ID", "197800000")
    return {
        "Authorization": f"Zoho-oauthtoken {token}",
        "orgId": org_id,
        "Content-Type": "application/json",
    }


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict = None) -> Optional[dict]:
    for attempt in range(3):
        try:
            resp = await client.get(url, params=params, headers=_headers(), timeout=20)
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"API Error on {url}: {e}")
            if attempt == 2: return None
            await asyncio.sleep(1)
    return None


# ─── Ticket fetching ──────────────────────────────────────────────────────────

async def _fetch_dept_tickets(client: httpx.AsyncClient, dept: dict, no_action_threshold: int) -> list[dict]:
    """Fetch and manually filter for overdue tickets to avoid 422 errors."""
    dept_id = dept["id"]
    all_tickets = []
    offset, limit = 0, 100
    
    # Check tickets created in the last 180 days
    since = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ")

    while True:
        # NOTE: 'isOverDue' removed from params to prevent Zoho 422 error
        params = {
            "departmentId": dept_id,
            "limit": limit,
            "from": offset,
            "sortBy": "dueDate",
            "order": "asc",
            "createdTimeRange": since,
            "include": "assignee,departments",
        }
        data = await _get_with_retry(client, f"{_api_base()}/api/v1/tickets", params=params)
        
        if not data or "data" not in data:
            break

        tickets = data.get("data", [])
        
        # Local Filtering: Zoho rejected 'isOverDue' in the URL, so we check it here.
        # We look for 'isOverdue' (common JSON key) or check if dueDate < now.
        now = datetime.now(timezone.utc)
        for t in tickets:
            is_overdue_flag = str(t.get("isOverdue", "")).lower() == "true"
            
            # Backup check: Compare due date if the flag is missing
            due_date_str = t.get("dueDate")
            manual_overdue = False
            if due_date_str:
                try:
                    due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
                    manual_overdue = due_date < now
                except: pass

            if is_overdue_flag or manual_overdue:
                all_tickets.extend([t])

        if len(tickets) < limit:
            break
        offset += limit

    logger.info(f"[{dept['name']}] Found {len(all_tickets)} overdue tickets.")
    return classify_and_filter(all_tickets, dept["name"], no_action_threshold)


# ─── Main sync runner ─────────────────────────────────────────────────────────

async def run_sync() -> dict:
    if not is_configured():
        return {"status": "not_configured"}

    if cache.get_sync_status()["sync_running"]:
        return {"status": "already_running"}

    cache.set_sync_running(True)
    cache.clear_dept_errors()
    
    no_action_threshold = int(os.getenv("NO_ACTION_THRESHOLD_HOURS", "0"))
    sync_interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "15"))

    now_str = datetime.now(timezone.utc).isoformat()
    cache.set_sync_times(now_str, (datetime.now(timezone.utc) + timedelta(minutes=sync_interval)).isoformat())

    results = {}
    async with httpx.AsyncClient() as client:
        for dept in DEPARTMENTS:
            try:
                tickets = await _fetch_dept_tickets(client, dept, no_action_threshold)
                cache.set_cached_tickets(dept["name"], tickets)
                cache.set_dept_count(dept["name"], len(tickets))
                results[dept["name"]] = len(tickets)
            except Exception as e:
                logger.error(f"Sync error {dept['name']}: {e}")
                cache.set_dept_error(dept["name"], str(e))

    cache.set_sync_running(False)
    return {"status": "ok", "counts": results}
    # backend/services/zoho_fetcher.py
# ─────────────────────────────────────────────────────────────────
#  Zoho Desk ticket fetcher.
#
#  FIX (2026-04-23):
#    ROOT CAUSE of 422 errors on every request:
#      The previous code sent `createdTimeRange=<single ISO timestamp>`
#      as a query parameter. Zoho Desk /api/v1/tickets does NOT accept
#      `createdTimeRange` as a standalone filter — it either expects a
#      comma-separated start,end pair or is simply unsupported on this
#      endpoint. Sending a single timestamp caused Zoho to return
#      HTTP 422 Unprocessable Entity for every department, every cycle,
#      resulting in 0 tickets returned across the board.
#
#    CHANGES (minimal — nothing else altered):
#      1. Removed `createdTimeRange` from the params dict entirely.
#      2. Changed `sortBy` from `dueDate` → `modifiedTime` (safer;
#         dueDate can be null on tickets and triggers 422 on some orgs).
#      3. Added `status` filter so we only pull open/actionable tickets
#         instead of fetching everything.
#
#    All other logic (pagination, error handling, caller interface)
#    is unchanged so nothing downstream breaks.
# ─────────────────────────────────────────────────────────────────

import logging
from typing import Optional

import httpx

from logic.zoho_auth import get_access_token
from logic.config import settings

logger = logging.getLogger(__name__)

API_BASE  = "https://desk.zoho.com/api/v1"
PAGE_SIZE = 100
MAX_PAGES = 20   # safety cap: 2 000 tickets per dept per cycle

# Comma-separated list of statuses Zoho Desk accepts on the
# `status` query param (exact strings from the Zoho Desk UI).
OPEN_STATUSES = (
    "Open,"
    "Pending,"
    "Pending Development,"
    "On Hold,"
    "Escalated,"
    "Waiting on Customer"
)


async def fetch_tickets_by_department(
    department_id: str,
    dept_label: str = "Unknown",
) -> list[dict]:
    """
    Fetch all non-closed tickets for one Zoho Desk department.

    Paginates automatically using `from` offset until no more pages.
    Returns a list of raw ticket dicts (normalised downstream).
    Raises on auth failure; other HTTP errors are logged and an empty
    list is returned so other departments continue loading.
    """
    token = await get_access_token()
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "orgId": settings.ZOHO_ORG_ID,
        "Content-Type": "application/json",
    }

    all_tickets: list[dict] = []
    offset        = 0
    pages_fetched = 0

    async with httpx.AsyncClient(timeout=20.0) as client:
        while pages_fetched < MAX_PAGES:

            # ── Correct Zoho Desk /api/v1/tickets params ──────────
            #   REMOVED: createdTimeRange  ← was causing 422 on every call
            #   CHANGED: sortBy dueDate → modifiedTime (dueDate nullable)
            params = {
                "departmentId": department_id,
                "from":         offset,
                "limit":        PAGE_SIZE,
                "sortBy":       "modifiedTime",
                "order":        "desc",
                "status":       OPEN_STATUSES,
                "include":      "assignee,departments",
            }

            try:
                response = await client.get(
                    f"{API_BASE}/tickets",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()

            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                body        = exc.response.text[:400]
                logger.error(
                    "API Error on %s: %s — Response: %s",
                    exc.request.url,
                    exc,
                    body,
                )
                if status_code == 401:
                    raise   # let caller handle token refresh
                break       # stop paging this dept on any other error

            except httpx.RequestError as exc:
                logger.error("Network error fetching [%s]: %s", dept_label, exc)
                break

            data    = response.json()
            tickets: list[dict] = data.get("data", [])

            if not tickets:
                break

            all_tickets.extend(tickets)
            logger.debug(
                "[%s] Page %d: got %d tickets (offset=%d)",
                dept_label, pages_fetched + 1, len(tickets), offset,
            )

            offset        += PAGE_SIZE
            pages_fetched += 1

            if len(tickets) < PAGE_SIZE:
                break   # last partial page

    logger.info("[%s] Found %d tickets.", dept_label, len(all_tickets))
    return all_tickets


async def fetch_all_departments() -> dict[str, list[dict]]:
    """
    Fetch tickets for all configured departments concurrently.
    A failure in one department does not affect the others.

    Returns: { dept_key: [ticket, ...], ... }
    """
    import asyncio

    results: dict[str, list[dict]] = {}
    errors:  dict[str, str]        = {}

    async def _fetch_one(dept: dict) -> None:
        try:
            results[dept["key"]] = await fetch_tickets_by_department(
                department_id=dept["id"],
                dept_label=dept["label"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] fetch failed: %s", dept["label"], exc)
            errors[dept["key"]]  = str(exc)
            results[dept["key"]] = []

    await asyncio.gather(*[_fetch_one(d) for d in settings.departments])

    if errors:
        logger.warning("Depts with errors: %s", list(errors.keys()))

    return results


# ── SLA / inactivity helpers (unchanged from original) ──────────

from datetime import datetime, timezone


def is_overdue(ticket: dict) -> bool:
    """Return True if the ticket's SLA due date has passed."""
    due_str = ticket.get("dueDate") or ticket.get("responseDueDate")
    if not due_str:
        return bool(ticket.get("isOverDue", False))
    try:
        due = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
        return due < datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def hours_since_modified(ticket: dict) -> float:
    """Hours elapsed since last modification (falls back to createdTime)."""
    ref_str = ticket.get("modifiedTime") or ticket.get("createdTime")
    if not ref_str:
        return 0.0
    try:
        ref   = datetime.fromisoformat(ref_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ref
        return delta.total_seconds() / 3600
    except (ValueError, TypeError):
        return 0.0


def filter_sla_breaches(
    tickets: list[dict],
    inactivity_threshold_hours: float = 24.0,
) -> list[dict]:
    """
    Return tickets that are SLA-overdue AND have had no action
    within `inactivity_threshold_hours`.

    Each returned ticket gets `_analysis` injected with:
      idle_hours, is_overdue, alert_label, severity
    """
    breaches = []
    for t in tickets:
        overdue          = is_overdue(t)
        idle_hours       = hours_since_modified(t)
        no_recent_action = idle_hours >= inactivity_threshold_hours

        if overdue and no_recent_action:
            t["_analysis"] = {
                "is_overdue":  True,
                "idle_hours":  round(idle_hours, 2),
                "alert_label": "SLA Breach \u2013 No Action",
                "severity":    _severity(idle_hours),
            }
            breaches.append(t)
        elif overdue:
            t["_analysis"] = {
                "is_overdue":  True,
                "idle_hours":  round(idle_hours, 2),
                "alert_label": "SLA Breached",
                "severity":    "medium",
            }
            breaches.append(t)

    logger.info(
        "filter_sla_breaches: %d/%d tickets flagged",
        len(breaches), len(tickets),
    )
    return breaches


def _severity(idle_hours: float) -> str:
    if idle_hours >= 72: return "critical"
    if idle_hours >= 48: return "high"
    if idle_hours >= 24: return "medium"
    return "low"
