"""
SLA Breach Processor
Classifies tickets from Zoho Desk API by breach status and severity.
"""
import os
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Severity thresholds in hours overdue
SEVERITY_CRITICAL_HOURS = float(os.getenv("SEVERITY_CRITICAL_HOURS", "72"))
SEVERITY_MODERATE_HOURS = float(os.getenv("SEVERITY_MODERATE_HOURS", "24"))


def _parse_zoho_dt(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse Zoho's ISO 8601 datetime strings (e.g. '2024-04-15T09:05:00.000Z')."""
    if not dt_str:
        return None
    try:
        # Zoho returns strings like "2024-04-15T09:05:00.000Z"
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        try:
            # Fallback for non-standard formats
            from dateutil import parser
            return parser.parse(dt_str).replace(tzinfo=timezone.utc)
        except Exception:
            return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_sla_breached(ticket: dict) -> bool:
    """
    Returns True if the ticket has breached its SLA.
    Uses Zoho's isOverDue flag as primary signal,
    then falls back to comparing dueDate with now.
    """
    # Primary: Zoho's own isOverDue flag
    if ticket.get("isOverDue") is True:
        return True

    # Fallback: compare dueDate with current time
    due_date = _parse_zoho_dt(ticket.get("dueDate"))
    if due_date and due_date < _utcnow():
        return True

    return False


def hours_overdue(ticket: dict) -> float:
    """Calculate how many hours the ticket is past its due date."""
    due_date = _parse_zoho_dt(ticket.get("dueDate"))
    if not due_date:
        return 0.0
    delta = _utcnow() - due_date
    return max(0.0, delta.total_seconds() / 3600)


def is_no_action(ticket: dict, threshold_hours: Optional[int] = None) -> bool:
    """
    Returns True if the ticket has had no meaningful update since SLA breach.
    'No action' = modifiedTime hasn't changed beyond threshold_hours after dueDate.
    """
    if threshold_hours is None:
        threshold_hours = int(os.getenv("NO_ACTION_THRESHOLD_HOURS", "24"))

    modified_time = _parse_zoho_dt(ticket.get("modifiedTime"))
    due_date = _parse_zoho_dt(ticket.get("dueDate"))

    if not modified_time:
        return True  # No modification time = definitely no action

    now = _utcnow()

    # If ticket was modified after it became overdue — action exists
    # But only count it if the modification happened AFTER the due date has passed
    if due_date and modified_time > due_date:
        # There WAS an update after breach — check how recent
        hours_since_last_action = (now - modified_time).total_seconds() / 3600
        return hours_since_last_action >= threshold_hours
    else:
        # Modified time is BEFORE due date — no post-breach action
        return True


def get_breach_severity(hours: float) -> str:
    """Classify ticket severity based on hours overdue."""
    if hours >= SEVERITY_CRITICAL_HOURS:
        return "critical"
    elif hours >= SEVERITY_MODERATE_HOURS:
        return "moderate"
    elif hours > 0:
        return "watch"
    return "normal"


def normalize_ticket(raw: dict, dept_name: str) -> dict:
    """
    Map Zoho API ticket fields to our normalized internal schema.
    Handles missing fields gracefully.
    """
    overdue_hrs = hours_overdue(raw)
    severity = get_breach_severity(overdue_hrs)

    # Build Zoho Desk direct link
    ticket_id = raw.get("id", "")
    zoho_url = f"https://desk.zoho.com/support/aditadvertising/ShowHomePage.do#Cases/dv/{ticket_id}"

    # Assignee name
    assignee_obj = raw.get("assignee") or {}
    assignee_name = assignee_obj.get("firstName", "") + " " + assignee_obj.get("lastName", "")
    assignee_name = assignee_name.strip() or "Unassigned"

    # Priority
    priority = raw.get("priority") or "Medium"

    return {
        "id": ticket_id,
        "ticketNumber": raw.get("ticketNumber", ""),
        "subject": raw.get("subject", "No Subject"),
        "status": raw.get("status", "Open"),
        "assignee": assignee_name,
        "assigneeId": assignee_obj.get("id"),
        "priority": priority,
        "department": dept_name,
        "sla_status": "breached" if raw.get("isOverDue") else "at_risk",
        "created_time": raw.get("createdTime"),
        "modified_time": raw.get("modifiedTime"),
        "due_date": raw.get("dueDate"),
        "hours_overdue": round(overdue_hrs, 1),
        "severity": severity,
        "zoho_url": zoho_url,
    }


def classify_and_filter(tickets: list[dict], dept_name: str, threshold_hours: int = 24) -> list[dict]:
    """
    Full pipeline: filter to only SLA-breached + no-action tickets, normalize, and sort.
    """
    results = []
    for t in tickets:
        try:
            if is_sla_breached(t) and is_no_action(t, threshold_hours):
                normalized = normalize_ticket(t, dept_name)
                results.append(normalized)
        except Exception as e:
            logger.warning(f"Error classifying ticket {t.get('id')}: {e}")

    # Sort: critical first, then by hours_overdue descending
    severity_order = {"critical": 0, "moderate": 1, "watch": 2, "normal": 3}
    results.sort(key=lambda t: (severity_order.get(t["severity"], 3), -t["hours_overdue"]))
    return results
