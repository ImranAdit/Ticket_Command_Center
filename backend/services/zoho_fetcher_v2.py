"""
Zoho Desk API Fetcher Service — v2
────────────────────────────────────────────────────────────────────────────────
Drop-in replacement for zoho_fetcher.run_sync() that fixes the 422 errors
caused by unsupported query parameters (isOverDue, createdTimeRange) in the
Zoho Desk GET /api/v1/tickets endpoint.

Strategy:
  • Only use documented/supported params: departmentId, status, limit, from,
    sortBy, order, include.
  • Fetch all Open + On Hold tickets per department (paginated).
  • Let sla_processor.classify_and_filter() handle SLA-breach detection
    and "no-action" logic locally — no server-side filter needed.

The original zoho_fetcher.py is left completely untouched.
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
# Mirrors the original fetcher — report_id kept for reference only.
DEPARTMENTS: list[dict] = [
    {"name": "VoIP",         "zoho_name": "VoIP",         "id": None,
     "report_id": "197800000150281001"},
    {"name": "T1 Tech",      "zoho_name": "T1 Tech",      "id": None,
     "report_id": "197800000194883033"},
    {"name": "T2 Core Tech", "zoho_name": "T2 Core Tech", "id": None,
     "report_id": "197800000150281341"},
    {"name": "Adit Pay",     "zoho_name": "Adit Pay",     "id": None,
     "report_id": "197800000313746651"},
]

# Ticket statuses to pull (open + on-hold covers all potentially overdue work)
FETCH_STATUSES = ["Open", "On Hold"]

_org_id: Optional[str] = None
_dept_ids_resolved = False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _api_base() -> str:
    dc = os.getenv("ZOHO_DC", "com")
    mapping = {
        "com": "https://desk.zoho.com",
        "eu":  "https://desk.zoho.eu",
        "in":  "https://desk.zoho.in",
        "au":  "https://desk.zoho.com.au",
        "jp":  "https://desk.zoho.jp",
    }
    return mapping.get(dc, "https://desk.zoho.com")


def _headers() -> dict:
    token = get_access_token()
    org_id = os.getenv("ZOHO_ORG_ID") or _org_id or ""
    return {
        "Authorization": f"Zoho-oauthtoken {token}",
        "orgId": org_id,
        "Content-Type": "application/json",
    }


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict = None,
    retries: int = 3,
) -> Optional[dict]:
    """GET with exponential back-off on rate-limits (429) and server errors (5xx)."""
    delay = 2
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=_headers(), timeout=20)
            if resp.status_code == 429:
                logger.warning(f"Rate limited on {url}, waiting {delay}s…")
                await asyncio.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            body = e.response.text[:300]
            logger.error(f"API Error on {url}: {e} | body: {body}")
            if status >= 500 and attempt < retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error on {url}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return None
    return None


# ─── Org / Department resolution ──────────────────────────────────────────────

async def _resolve_org_id(client: httpx.AsyncClient) -> Optional[str]:
    global _org_id
    if _org_id:
        return _org_id

    env_org = os.getenv("ZOHO_ORG_ID")
    if env_org:
        _org_id = env_org
        return _org_id

    data = await _get_with_retry(client, f"{_api_base()}/api/v1/organizations")
    if data and data.get("data"):
        _org_id = str(data["data"][0]["id"])
        logger.info(f"[v2] Resolved orgId: {_org_id}")
        return _org_id
    return None


async def _resolve_dept_ids(client: httpx.AsyncClient) -> None:
    global _dept_ids_resolved
    if _dept_ids_resolved:
        return

    data = await _get_with_retry(
        client, f"{_api_base()}/api/v1/departments", params={"limit": 100}
    )
    if not data or "data" not in data:
        logger.error("[v2] Could not resolve department IDs from Zoho")
        return

    zoho_depts = {d["name"]: d["id"] for d in data["data"]}
    for dept in DEPARTMENTS:
        matched_id = zoho_depts.get(dept["zoho_name"])
        if not matched_id:
            for name, did in zoho_depts.items():
                if dept["zoho_name"].lower() in name.lower():
                    matched_id = did
                    break
        if matched_id:
            dept["id"] = str(matched_id)
            logger.info(f"[v2] Dept '{dept['name']}' → ID {matched_id}")
        else:
            logger.warning(
                f"[v2] Could not find dept '{dept['name']}'. "
                f"Available: {list(zoho_depts.keys())}"
            )

    _dept_ids_resolved = True


# ─── Ticket fetching ───────────────────────────────────────────────────────────

async def _fetch_dept_tickets_for_status(
    client: httpx.AsyncClient,
    dept_id: str,
    status: str,
) -> list[dict]:
    """
    Paginate through all tickets of a given status in one department.
    Uses ONLY documented Zoho Desk GET /api/v1/tickets query params.
    """
    tickets: list[dict] = []
    offset = 0
    limit = 100
    max_offset = 4900  # Zoho caps `from` at 4999

    while offset <= max_offset:
        params = {
            "departmentId": dept_id,
            "status": status,
            "limit": limit,
            "from": offset,
            "sortBy": "dueDate",
            "order": "asc",
            "include": "assignee,departments",
        }
        data = await _get_with_retry(
            client, f"{_api_base()}/api/v1/tickets", params=params
        )
        if not data:
            break

        page = data.get("data", [])
        tickets.extend(page)

        if len(page) < limit:
            break  # Last page
        offset += limit

    return tickets


async def _fetch_dept_tickets(
    client: httpx.AsyncClient,
    dept: dict,
    no_action_threshold: int,
) -> list[dict]:
    """Fetch all open/on-hold tickets for one department, then classify locally."""
    dept_id = dept["id"]
    if not dept_id:
        logger.warning(f"[v2] No dept ID for '{dept['name']}', skipping")
        return []

    all_raw: list[dict] = []
    for status in FETCH_STATUSES:
        page_tickets = await _fetch_dept_tickets_for_status(client, dept_id, status)
        logger.info(
            f"[v2][{dept['name']}] status='{status}' → {len(page_tickets)} tickets fetched"
        )
        all_raw.extend(page_tickets)

    logger.info(f"[v2][{dept['name']}] Total raw tickets: {len(all_raw)}")

    # Deduplicate (same ticket can appear in multiple status queries if race)
    seen: set[str] = set()
    unique: list[dict] = []
    for t in all_raw:
        tid = t.get("id")
        if tid and tid not in seen:
            seen.add(tid)
            unique.append(t)

    # SLA + no-action filter via existing sla_processor
    processed = classify_and_filter(unique, dept["name"], no_action_threshold)
    logger.info(
        f"[v2][{dept['name']}] {len(processed)} actionable SLA-breach tickets after filter"
    )
    return processed


# ─── Main sync runner ──────────────────────────────────────────────────────────

async def run_sync() -> dict:
    """
    Full sync cycle (v2): fetch all dept tickets with valid API params,
    apply SLA logic locally, update cache.
    Returns summary dict with counts and any errors.
    """
    if not is_configured():
        msg = "Zoho credentials not configured — sync skipped"
        logger.warning(msg)
        cache.append_log("WARN", msg)
        return {"status": "not_configured", "message": msg}

    if cache.get_sync_status()["sync_running"]:
        logger.info("[v2] Sync already in progress, skipping")
        return {"status": "already_running"}

    cache.set_sync_running(True)
    cache.clear_dept_errors()
    no_action_threshold = int(os.getenv("NO_ACTION_THRESHOLD_HOURS", "24"))
    sync_interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "15"))

    now_str = datetime.now(timezone.utc).isoformat()
    next_str = (datetime.now(timezone.utc) + timedelta(minutes=sync_interval)).isoformat()
    cache.set_sync_times(now_str, next_str)
    cache.append_log("INFO", f"[v2] Sync started at {now_str}")

    results = {}
    try:
        async with httpx.AsyncClient() as client:
            org_id = await _resolve_org_id(client)
            if not org_id:
                msg = "[v2] Could not resolve Zoho org ID — check credentials"
                logger.error(msg)
                cache.append_log("ERROR", msg)
                cache.set_sync_running(False)
                return {"status": "error", "message": msg}

            await _resolve_dept_ids(client)

            for dept in DEPARTMENTS:
                try:
                    tickets = await _fetch_dept_tickets(client, dept, no_action_threshold)
                    cache.set_cached_tickets(dept["name"], tickets)
                    cache.set_dept_count(dept["name"], len(tickets))
                    results[dept["name"]] = len(tickets)
                    cache.append_log(
                        "INFO",
                        f"[v2][{dept['name']}] {len(tickets)} actionable SLA breaches cached",
                        dept=dept["name"],
                    )
                except Exception as e:
                    err = str(e)
                    logger.error(f"[v2] Sync error for {dept['name']}: {err}")
                    cache.set_dept_error(dept["name"], err)
                    cache.append_log(
                        "ERROR",
                        f"[v2][{dept['name']}] Sync failed: {err}",
                        dept=dept["name"],
                    )

    finally:
        cache.set_sync_running(False)

    cache.append_log("INFO", f"[v2] Sync complete. Results: {results}")
    logger.info(f"[v2] Sync complete: {results}")
    return {"status": "ok", "counts": results, "synced_at": now_str}
