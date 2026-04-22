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
