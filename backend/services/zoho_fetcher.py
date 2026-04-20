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
# Maps display name → Zoho Desk departmentId (resolved at startup via API)
DEPARTMENTS: list[dict] = [
    {"name": "VoIP",        "zoho_name": "VoIP",         "id": None,
     "report_id": "197800000150281001"},
    {"name": "T1 Tech",     "zoho_name": "T1 Tech",      "id": None,
     "report_id": "197800000194883033"},
    {"name": "T2 Core Tech","zoho_name": "T2 Core Tech", "id": None,
     "report_id": "197800000150281341"},
    {"name": "Adit Pay",    "zoho_name": "Adit Pay",     "id": None,
     "report_id": "197800000313746651"},
]

_org_id: Optional[str] = None
_dept_ids_resolved = False

# ─── Helpers ─────────────────────────────────────────────────────────────────

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


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict = None,
                           retries: int = 3) -> Optional[dict]:
    """GET with exponential backoff on rate limits (429) and server errors (5xx)."""
    delay = 2
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=_headers(), timeout=20)
            if resp.status_code == 429:
                logger.warning(f"Rate limited on {url}, waiting {delay}s...")
                await asyncio.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500 and attempt < retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            logger.error(f"HTTP {e.response.status_code} on {url}: {e.response.text[:200]}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error on {url}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return None
    return None


# ─── Org / Department resolution ─────────────────────────────────────────────

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
        logger.info(f"Resolved orgId: {_org_id}")
        return _org_id
    return None


async def _resolve_dept_ids(client: httpx.AsyncClient) -> None:
    global _dept_ids_resolved
    if _dept_ids_resolved:
        return

    data = await _get_with_retry(client, f"{_api_base()}/api/v1/departments",
                                  params={"limit": 100})
    if not data or "data" not in data:
        logger.error("Could not resolve department IDs from Zoho")
        return

    zoho_depts = {d["name"]: d["id"] for d in data["data"]}
    for dept in DEPARTMENTS:
        # Match by exact name or partial match
        matched_id = zoho_depts.get(dept["zoho_name"])
        if not matched_id:
            # Try case-insensitive partial match
            for name, did in zoho_depts.items():
                if dept["zoho_name"].lower() in name.lower():
                    matched_id = did
                    break
        if matched_id:
            dept["id"] = str(matched_id)
            logger.info(f"Dept '{dept['name']}' → ID {matched_id}")
        else:
            logger.warning(f"Could not find dept '{dept['name']}' in Zoho. Available: {list(zoho_depts.keys())}")

    _dept_ids_resolved = True


# ─── Ticket fetching ──────────────────────────────────────────────────────────

async def _fetch_dept_tickets(client: httpx.AsyncClient, dept: dict,
                               no_action_threshold: int) -> list[dict]:
    """Fetch all SLA-breached tickets for one department via pagination."""
    dept_id = dept["id"]
    if not dept_id:
        logger.warning(f"No dept ID for {dept['name']}, skipping fetch")
        return []

    all_tickets = []
    offset = 0
    limit = 100

    # Date filter: last 1 year
    since = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")

    while True:
        params = {
            "departmentId": dept_id,
            "isOverDue": "true",
            "limit": limit,
            "from": offset,
            "sortBy": "dueDate",
            "order": "asc",
            "createdTimeRange": since,
            "include": "assignee,departments",
        }
        data = await _get_with_retry(client, f"{_api_base()}/api/v1/tickets", params=params)
        if not data:
            break

        tickets = data.get("data", [])
        all_tickets.extend(tickets)

        # Check if more pages exist
        total = data.get("count", len(tickets))
        if len(tickets) < limit or offset + limit >= total:
            break
        offset += limit

    logger.info(f"[{dept['name']}] Fetched {len(all_tickets)} overdue tickets raw")

    # Classify: SLA breached AND no action
    processed = classify_and_filter(all_tickets, dept["name"], no_action_threshold)
    logger.info(f"[{dept['name']}] {len(processed)} tickets after SLA+no-action filter")
    return processed


# ─── Main sync runner ─────────────────────────────────────────────────────────

async def run_sync() -> dict:
    """
    Full sync cycle: fetch all dept tickets, apply SLA logic, update cache.
    Returns summary dict with counts and any errors.
    """
    if not is_configured():
        msg = "Zoho credentials not configured — sync skipped"
        logger.warning(msg)
        cache.append_log("WARN", msg)
        return {"status": "not_configured", "message": msg}

    if cache.get_sync_status()["sync_running"]:
        logger.info("Sync already in progress, skipping")
        return {"status": "already_running"}

    cache.set_sync_running(True)
    cache.clear_dept_errors()
    no_action_threshold = int(os.getenv("NO_ACTION_THRESHOLD_HOURS", "24"))
    sync_interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "15"))

    now_str = datetime.now(timezone.utc).isoformat()
    next_str = (datetime.now(timezone.utc) + timedelta(minutes=sync_interval)).isoformat()
    cache.set_sync_times(now_str, next_str)
    cache.append_log("INFO", f"Sync started at {now_str}")

    results = {}
    try:
        async with httpx.AsyncClient() as client:
            # Resolve org and dept IDs on first run
            org_id = await _resolve_org_id(client)
            if not org_id:
                msg = "Could not resolve Zoho org ID — check credentials"
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
                    cache.append_log("INFO",
                        f"[{dept['name']}] {len(tickets)} actionable SLA breaches cached",
                        dept=dept["name"])
                except Exception as e:
                    err = str(e)
                    logger.error(f"Sync error for {dept['name']}: {err}")
                    cache.set_dept_error(dept["name"], err)
                    cache.append_log("ERROR", f"[{dept['name']}] Sync failed: {err}",
                                     dept=dept["name"])

    finally:
        cache.set_sync_running(False)

    cache.append_log("INFO", f"Sync complete. Results: {results}")
    return {"status": "ok", "counts": results, "synced_at": now_str}
