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
_last_api_error: Optional[str] = None
_dept_ids_resolved = False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _api_base() -> str:
    dc = (os.getenv("ZOHO_DC") or "com").strip().lower()
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
    org_id = (os.getenv("ZOHO_ORG_ID") or "").strip() or _org_id or ""
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
    global _last_api_error
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
            _last_api_error = f"Zoho {status}: {body}"
            if status >= 500 and attempt < retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error on {url}: {e}")
            _last_api_error = f"Request error: {e}"
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

    env_org = (os.getenv("ZOHO_ORG_ID") or "").strip()
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
    dept_id: Optional[str],
    status: str,
) -> list[dict]:
    """
    Paginate through all tickets of a given status — in one department, or
    across ALL departments when dept_id is None.
    Uses ONLY documented Zoho Desk GET /api/v1/tickets query params.
    """
    tickets: list[dict] = []
    offset = 0
    limit = 100
    max_offset = 4900  # Zoho caps `from` at 4999
    use_sort = True

    while offset <= max_offset:
        params = {
            "status": status,
            "limit": limit,
            "from": offset,
            "include": "assignee,departments",
        }
        if dept_id:
            params["departmentId"] = dept_id
        if use_sort:
            # ascending → most-overdue first, so they survive the 5000-row cap
            params["sortBy"] = "dueDate"
        data = await _get_with_retry(
            client, f"{_api_base()}/api/v1/tickets", params=params
        )
        if data is None:
            if offset == 0 and use_sort and "422" in (_last_api_error or ""):
                logger.warning("[v2] Zoho rejected sortBy=dueDate, retrying unsorted")
                use_sort = False
                continue
            if offset == 0:
                # Surface the failure instead of silently reporting "All clear"
                raise RuntimeError(_last_api_error or "Zoho tickets request failed")
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
        raise RuntimeError(
            f"Department '{dept['zoho_name']}' not found in Zoho Desk (check name / Desk.basic.READ scope)"
        )

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


def _match_dept(zoho_dept_name: str) -> Optional[dict]:
    """Map a Zoho department name onto one of our configured DEPARTMENTS."""
    n = (zoho_dept_name or "").strip().lower()
    if not n:
        return None
    for d in DEPARTMENTS:
        if d["zoho_name"].lower() == n:
            return d
    for d in DEPARTMENTS:
        z = d["zoho_name"].lower()
        if z in n or n in z:
            return d
    return None


async def _fetch_all_depts_via_tickets(
    client: httpx.AsyncClient,
    no_action_threshold: int,
) -> dict[str, list[dict]]:
    """
    Fallback when department IDs can't be resolved (e.g. the OAuth token lacks
    Desk.basic.READ → 403 SCOPE_MISMATCH on /departments). Pulls open/on-hold
    tickets across all departments (needs only Desk.tickets.READ) and groups
    them by the department name Zoho returns on each ticket.
    """
    raw: list[dict] = []
    for status in FETCH_STATUSES:
        try:
            page = await _fetch_dept_tickets_for_status(client, None, status)
        except RuntimeError as e:
            if status == FETCH_STATUSES[0]:
                raise
            logger.warning(f"[v2] Skipping status '{status}': {e}")
            cache.append_log("WARN", f"[v2] Skipping status '{status}': {e}")
            continue
        logger.info(f"[v2][all depts] status='{status}' → {len(page)} tickets fetched")
        raw.extend(page)

    grouped: dict[str, list[dict]] = {d["name"]: [] for d in DEPARTMENTS}
    seen_ids: set[str] = set()
    names_seen: dict[str, int] = {}
    for t in raw:
        tid = t.get("id")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        zname = ((t.get("department") or {}).get("name") or "").strip()
        names_seen[zname or "(none)"] = names_seen.get(zname or "(none)", 0) + 1
        d = _match_dept(zname)
        if d:
            if not d["id"] and t.get("departmentId"):
                d["id"] = str(t["departmentId"])  # learn the real ID for next time
            grouped[d["name"]].append(t)

    msg = f"[v2] Zoho department names on open tickets: {names_seen}"
    logger.info(msg)
    cache.append_log("INFO", msg)

    return {
        name: classify_and_filter(tickets, name, no_action_threshold)
        for name, tickets in grouped.items()
    }


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
        if not get_access_token():
            from logic.zoho_auth import get_last_error
            msg = get_last_error() or "Could not get Zoho access token"
            logger.error(f"[v2] {msg}")
            cache.append_log("ERROR", f"[v2] {msg}")
            for dept in DEPARTMENTS:
                cache.set_dept_error(dept["name"], msg)
            return {"status": "error", "message": msg}

        async with httpx.AsyncClient() as client:
            org_id = await _resolve_org_id(client)
            if not org_id:
                msg = f"Could not resolve Zoho org ID — {_last_api_error or 'check credentials'}"
                logger.error(msg)
                cache.append_log("ERROR", msg)
                for dept in DEPARTMENTS:
                    cache.set_dept_error(dept["name"], msg)
                return {"status": "error", "message": msg}

            await _resolve_dept_ids(client)

            if any(not d["id"] for d in DEPARTMENTS):
                logger.warning("[v2] Department IDs unresolved — using all-department ticket fallback")
                cache.append_log("WARN", "[v2] Department IDs unresolved — grouping tickets by department name instead")
                try:
                    by_dept = await _fetch_all_depts_via_tickets(client, no_action_threshold)
                except Exception as e:
                    err = str(e)
                    logger.error(f"[v2] Fallback sync failed: {err}")
                    for dept in DEPARTMENTS:
                        cache.set_dept_error(dept["name"], err)
                    cache.append_log("ERROR", f"[v2] Fallback sync failed: {err}")
                    return {"status": "error", "message": err}
                for name, tickets in by_dept.items():
                    cache.set_cached_tickets(name, tickets)
                    cache.set_dept_count(name, len(tickets))
                    results[name] = len(tickets)
                cache.append_log("INFO", f"[v2] Sync complete (fallback). Results: {results}")
                return {"status": "ok", "counts": results, "synced_at": now_str, "mode": "fallback"}

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
