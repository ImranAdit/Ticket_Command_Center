"""
Sync Router — exposes sync status, ticket data, manual trigger, and logs.
"""
import os
import asyncio
from fastapi import APIRouter, Query, BackgroundTasks
from typing import Optional

from logic import cache
from logic.zoho_auth import is_configured
from services import zoho_fetcher

router = APIRouter()


@router.get("/status")
def get_sync_status():
    """Returns current sync metadata: last/next sync time, dept counts, errors."""
    status = cache.get_sync_status()
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
def get_tickets(dept: Optional[str] = Query(None, description="Filter by department name")):
    """
    Returns cached SLA-breached tickets with no action.
    Optionally filter by ?dept=VoIP (etc.)
    """
    all_data = cache.get_all_cached_tickets()

    if dept:
        filtered = all_data.get(dept, [])
        return {
            "dept": dept,
            "count": len(filtered),
            "tickets": filtered,
            "sync_status": cache.get_sync_status(),
        }

    # Return all departments grouped
    grouped = {}
    total = 0
    for dept_name, tickets in all_data.items():
        grouped[dept_name] = tickets
        total += len(tickets)

    # Also include departments with no data in cache yet
    from services.zoho_fetcher import DEPARTMENTS
    for d in DEPARTMENTS:
        if d["name"] not in grouped:
            grouped[d["name"]] = []

    return {
        "total": total,
        "departments": grouped,
        "sync_status": cache.get_sync_status(),
    }


@router.get("/config")
def get_config():
    """Return current configurable thresholds."""
    return {
        "sync_interval_minutes": int(os.getenv("SYNC_INTERVAL_MINUTES", "15")),
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
