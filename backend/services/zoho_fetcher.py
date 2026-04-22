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
# Hardcoded IDs ensure the sync works even if Zoho department names are generic.
DEPARTMENTS: list[dict] = [
    {
        "name": "VoIP",
        "zoho_name": "Support",
        "id": "197800000150281001",
        "report_id": "197800000150281001"
    },
    {
        "name": "T1 Tech",
        "zoho_name": "Support",
        "id": "197800000194883033",
        "report_id": "197800000194883033"
    },
    {
        "name": "T2 Core Tech",
        "zoho_name": "Support",
        "id": "197800000150281341",
        "report_id": "197800000150281341"
    },
    {
        "name": "Adit Pay",
        "zoho_name": "Support",
        "id": "197800000204233645",
        "report_id": "197800000204233645"
    },
]

_org_id: Optional[str] = None
_dept_ids_resolved = True  # Set to True to skip name-based discovery

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
    # Prioritize Railway Variable ZOHO_ORG_ID, fallback to 197800000
    org_id = os.getenv("ZOHO_ORG_ID") or _org_id or "197800000"
    return {
        "Authorization": f"Zoho-oauthtoken {token}",
        "orgId": org_id,
        "Content-Type": "application/json",
    }


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict = None,
                           retries: int = 3) -> Optional[dict]:
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
    env_org = os.getenv("ZOHO_ORG_ID") or "197800000"
    _org_id = env_org
    return _org_id


async def _resolve_dept_ids(client: httpx.AsyncClient) -> None:
    # IDs are hardcoded in the DEPARTMENTS list above, so we skip dynamic resolution
    pass


# ─── Ticket fetching ──────────────────────────────────────────────────────────

async def _fetch_dept_tickets(client: httpx.AsyncClient, dept: dict,
                               no_action_threshold: int) -> list[dict]:
    dept_id = dept["id"]
    if not dept_id:
        return []

    all_tickets = []
    offset = 0
    limit = 100
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

        total = data.get("count", len(tickets))
        if len(tickets) < limit or offset + limit >= total:
            break
        offset += limit

    logger.info(f"[{dept['name']}] Fetched {len(all_tickets)} overdue tickets raw")
    processed = classify_and_filter(all_tickets, dept["name"], no_action_threshold)
    return processed


# ─── Main sync runner ─────────────────────────────────────────────────────────

async def run_sync() -> dict:
    if not is_configured():
        msg = "Zoho credentials not configured — sync skipped"
        logger.warning(msg)
        cache.append_log("WARN", msg)
        return {"status": "not_configured", "message": msg}

    if cache.get_sync_status()["sync_running"]:
        return {"status": "already_running"}

    cache.set_sync_running(True)
    cache.clear_dept_errors()
    
    # Logic to show tickets. Set NO_ACTION_THRESHOLD_HOURS=0 in Railway to see all overdue.
    no_action_threshold = int(os.getenv("NO_ACTION_THRESHOLD_HOURS", "24"))
    sync_interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "15"))

    now_str = datetime.now(timezone.utc).isoformat()
    next_str = (datetime.now(timezone.utc) + timedelta(minutes=sync_interval)).isoformat()
    cache.set_sync_times(now_str, next_str)

    results = {}
    try:
        async with httpx.AsyncClient() as client:
            # Org ID will resolve to 197800000 automatically
            await _resolve_org_id(client)

            for dept in DEPARTMENTS:
                try:
                    tickets = await _fetch_dept_tickets(client, dept, no_action_threshold)
                    cache.set_cached_tickets(dept["name"], tickets)
                    cache.set_dept_count(dept["name"], len(tickets))
                    results[dept["name"]] = len(tickets)
                    cache.append_log("INFO", f"[{dept['name']}] {len(tickets)} actionable SLA breaches cached", dept=dept["name"])
                except Exception as e:
                    err = str(e)
                    logger.error(f"Sync error for {dept['name']}: {err}")
                    cache.set_dept_error(dept["name"], err)

    finally:
        cache.set_sync_running(False)

    return {"status": "ok", "counts": results, "synced_at": now_str}
