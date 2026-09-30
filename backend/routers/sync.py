"""
Sync Router — exposes sync status, ticket data, manual trigger, and logs.
"""
import os
import asyncio
from fastapi import APIRouter, Query, BackgroundTasks, Request
from typing import Optional

from logic import cache
from logic.zoho_auth import is_configured
from services import zoho_fetcher_v2 as zoho_fetcher
from routers.auth import can_see_dept

router = APIRouter()


def _scoped_status(request: Request) -> dict:
    """Sync status limited to the departments this user may see."""
    status = cache.get_sync_status()
    for key in ("dept_counts", "dept_errors"):
        status[key] = {d: v for d, v in (status.get(key) or {}).items() if can_see_dept(request, d)}
    return status


@router.get("/status")
def get_sync_status(request: Request):
    """Returns current sync metadata: last/next sync time, dept counts, errors."""
    status = _scoped_status(request)
    return {
        "configured": is_configured(),
        **status,
    }


@router.post("/trigger")
async def trigger_sync(background_tasks: BackgroundTasks):
    """Manually trigger a sync cycle in the background."""
    if not is_configured():
        return {"status": "not_configured",
                "message": "Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN in .env"}

    if cache.get_sync_status()["sync_running"]:
        return {"status": "already_running", "message": "A sync is already in progress"}

    background_tasks.add_task(zoho_fetcher.run_sync)
    return {"status": "triggered", "message": "Sync started in background"}


@router.get("/tickets")
def get_tickets(request: Request, dept: Optional[str] = Query(None, description="Filter by department name")):
    """
    Returns cached SLA-breached tickets with no action.
    Optionally filter by ?dept=VoIP (etc.)
    Department-level users only ever receive their own departments.
    """
    all_data = {d: t for d, t in cache.get_all_cached_tickets().items() if can_see_dept(request, d)}

    if dept:
        filtered = all_data.get(dept, [])
        return {
            "dept": dept,
            "count": len(filtered),
            "tickets": filtered,
            "sync_status": _scoped_status(request),
        }

    # Return all departments grouped
    grouped = {}
    total = 0
    for dept_name, tickets in all_data.items():
        grouped[dept_name] = tickets
        total += len(tickets)

    # Also include departments with no data in cache yet
    from services.zoho_fetcher_v2 import DEPARTMENTS
    for d in DEPARTMENTS:
        if d["name"] not in grouped and can_see_dept(request, d["name"]):
            grouped[d["name"]] = []

    return {
        "total": total,
        "departments": grouped,
        "sync_status": _scoped_status(request),
    }


@router.get("/debug-env")
def debug_env():
    """
    Diagnostics: shows WHICH env vars this running container can see (names and
    true/false only — never values), plus which Railway service/env/commit is live.
    """
    from logic.zoho_auth import get_last_error
    required = ["ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"]
    optional = ["ZOHO_DC", "ZOHO_ORG_ID", "ZOHO_ACCOUNTS_URL", "NO_ACTION_THRESHOLD_HOURS"]
    return {
        "required_present": {k: bool((os.getenv(k) or "").strip()) for k in required},
        "optional_present": {k: bool((os.getenv(k) or "").strip()) for k in optional},
        "zoho_var_names_seen": sorted(k for k in os.environ if k.upper().startswith("ZOHO")),
        "railway_service": os.getenv("RAILWAY_SERVICE_NAME"),
        "railway_environment": os.getenv("RAILWAY_ENVIRONMENT_NAME"),
        "railway_commit": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "")[:7] or None,
        "last_token_error": get_last_error(),
    }


@router.get("/config")
def get_config():
    """Return current configurable thresholds."""
    return {
        "sync_interval_minutes": int(os.getenv("SYNC_INTERVAL_MINUTES", "5")),
        "no_action_threshold_hours": int(os.getenv("NO_ACTION_THRESHOLD_HOURS", "24")),
        "severity_critical_hours": float(os.getenv("SEVERITY_CRITICAL_HOURS", "72")),
        "severity_moderate_hours": float(os.getenv("SEVERITY_MODERATE_HOURS", "24")),
        "zoho_dc": os.getenv("ZOHO_DC", "com"),
    }


@router.get("/logs")
def get_logs():
    """Return last 100 sync log entries (newest first)."""
    return {
        "logs": cache.get_sync_log()
    }
