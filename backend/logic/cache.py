"""
In-memory TTL cache for ticket sync results.
Uses cachetools.TTLCache — thread-safe with lock.
"""
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Optional
from cachetools import TTLCache

# Max 10 departments, 30-minute TTL for ticket data
_ticket_cache: TTLCache = TTLCache(maxsize=10, ttl=1800)
_ticket_lock = Lock()

# Sync metadata
_sync_meta = {
    "last_sync_time": None,
    "next_sync_time": None,
    "sync_running": False,
    "dept_counts": {},
    "dept_errors": {},
}
_meta_lock = Lock()

# Sync activity log (last 100 entries)
_sync_log: list[dict] = []
_log_lock = Lock()


# ─── Ticket cache ──────────────────────────────────────────────────────────

def get_cached_tickets(dept: str) -> Optional[list]:
    with _ticket_lock:
        return _ticket_cache.get(dept)


def set_cached_tickets(dept: str, tickets: list) -> None:
    with _ticket_lock:
        _ticket_cache[dept] = tickets


def get_all_cached_tickets() -> dict[str, list]:
    with _ticket_lock:
        return {k: v for k, v in _ticket_cache.items()}


def clear_cache() -> None:
    with _ticket_lock:
        _ticket_cache.clear()


# ─── Sync metadata ─────────────────────────────────────────────────────────

def get_sync_status() -> dict:
    with _meta_lock:
        return {
            "last_sync_time": _sync_meta["last_sync_time"],
            "next_sync_time": _sync_meta["next_sync_time"],
            "sync_running": _sync_meta["sync_running"],
            "dept_counts": dict(_sync_meta["dept_counts"]),
            "dept_errors": dict(_sync_meta["dept_errors"]),
        }


def set_sync_running(running: bool) -> None:
    with _meta_lock:
        _sync_meta["sync_running"] = running


def set_sync_times(last: str, next_: str) -> None:
    with _meta_lock:
        _sync_meta["last_sync_time"] = last
        _sync_meta["next_sync_time"] = next_


def set_dept_count(dept: str, count: int) -> None:
    with _meta_lock:
        _sync_meta["dept_counts"][dept] = count


def set_dept_error(dept: str, error: str) -> None:
    with _meta_lock:
        _sync_meta["dept_errors"][dept] = error


def clear_dept_errors() -> None:
    with _meta_lock:
        _sync_meta["dept_errors"].clear()


# ─── Sync log ──────────────────────────────────────────────────────────────

def append_log(level: str, message: str, dept: Optional[str] = None) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        "dept": dept,
    }
    with _log_lock:
        _sync_log.append(entry)
        # Keep only last 100 entries
        if len(_sync_log) > 100:
            _sync_log.pop(0)


def get_sync_log() -> list[dict]:
    with _log_lock:
        return list(reversed(_sync_log))
