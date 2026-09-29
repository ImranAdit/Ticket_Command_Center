"""
SLA rules v3 — business-hours aware breach rules agreed with Support.

Business calendar: Mon–Fri 07:00–19:00 America/Chicago, minus HOLIDAYS.

Rules (evaluated per ticket, see evaluate_ticket):
  1. First response   — customer ticket with no agent reply: breach after 2 business hours
  2. Agent inactivity — assigned ticket with no reply/private note: at risk after 7 business hours
  3. Carried over     — same clock: breach after 24 weekday hours (weekends/holidays skipped)
                        once it has crossed into the next business day
  4. Pending Meeting  — no note/reply within 2 clock hours after the callback time found in
                        the latest private note (text or OCR'd calendar screenshot)
"Pending customer" pauses everything.

This module is pure (no network) so it can be unit-tested.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, date, time
from typing import Optional

import pytz

TZ = pytz.timezone("America/Chicago")
BUSINESS_START = 7   # 07:00 CT
BUSINESS_END = 19    # 19:00 CT

FIRST_RESPONSE_HOURS = float(os.getenv("SLA_FIRST_RESPONSE_HOURS", "2"))
AT_RISK_HOURS = float(os.getenv("SLA_AT_RISK_HOURS", "7"))
BREACH_WEEKDAY_HOURS = float(os.getenv("SLA_BREACH_HOURS", "24"))
CALLBACK_GRACE_HOURS = float(os.getenv("SLA_CALLBACK_GRACE_HOURS", "2"))

PAUSED_STATUSES = {"pending customer"}
MEETING_STATUSES = {"pending meeting"}


def _holidays() -> set[date]:
    raw = os.getenv("HOLIDAYS", "2026-11-26,2026-12-24,2026-12-25,2026-12-31")
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                out.add(date.fromisoformat(part))
            except ValueError:
                pass
    return out


HOLIDAYS = _holidays()


# ─── Time helpers ─────────────────────────────────────────────────────────────

def parse_dt(value) -> Optional[datetime]:
    """Parse Zoho ISO strings ('2026-09-28T17:33:00.000Z') → aware UTC datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else pytz.utc.localize(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def to_ct(dt: datetime) -> datetime:
    return dt.astimezone(TZ)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = TZ.localize(datetime.combine(d, time(BUSINESS_START)))
    end = TZ.localize(datetime.combine(d, time(BUSINESS_END)))
    return start, end


def business_hours_between(start: datetime, end: datetime) -> float:
    """Business hours (Mon–Fri 7–19 CT, excluding holidays) between two instants."""
    if not start or not end or end <= start:
        return 0.0
    s, e = to_ct(start), to_ct(end)
    total = 0.0
    d = s.date()
    while d <= e.date():
        if is_business_day(d):
            ds, de = _day_bounds(d)
            lo, hi = max(s, ds), min(e, de)
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600
        d += timedelta(days=1)
    return total


def weekday_hours_between(start: datetime, end: datetime) -> float:
    """Clock hours between two instants, skipping weekends and holidays entirely."""
    if not start or not end or end <= start:
        return 0.0
    s, e = to_ct(start), to_ct(end)
    total = 0.0
    d = s.date()
    while d <= e.date():
        if is_business_day(d):
            ds = TZ.localize(datetime.combine(d, time(0)))
            de = TZ.localize(datetime.combine(d + timedelta(days=1), time(0)))
            lo, hi = max(s, ds), min(e, de)
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600
        d += timedelta(days=1)
    return total


def next_business_open(dt: datetime) -> datetime:
    """Same instant if inside business hours, else the next 07:00 CT on a business day."""
    c = to_ct(dt)
    d = c.date()
    if is_business_day(d):
        ds, de = _day_bounds(d)
        if c < ds:
            return ds
        if c < de:
            return c
    d += timedelta(days=1)
    while not is_business_day(d):
        d += timedelta(days=1)
    return _day_bounds(d)[0]


def business_date(dt: datetime) -> date:
    """The business day an instant 'belongs' to (after-hours rolls forward)."""
    return to_ct(next_business_open(dt)).date()


# ─── Callback-time parsing ────────────────────────────────────────────────────

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH_WORDS = {w: i for i, names in enumerate([
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
    ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
    ("oct", "october"), ("nov", "november"), ("dec", "december")], 1) for w in names}


def _month(word: str) -> Optional[int]:
    return _MONTH_WORDS.get((word or "").lower().rstrip("."))


_WEEKDAYS = {d: i for i, d in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])}

_RE_RELATIVE = re.compile(r"\bin\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\b", re.I)
_RE_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
_RE_NOON = re.compile(r"\bnoon\b", re.I)
_RE_CAL = re.compile(
    r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+([a-z]{3,})\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?"
    r"\s*[·•.\-–,]?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*[–\-—to]+\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
    re.I)
_RE_MONTH_DAY = re.compile(r"\b([a-z]{3,})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s*(\d{4}))?", re.I)
_RE_NUM_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_RE_DAYWORD = re.compile(r"\b(today|tonight|tomorrow|tmrw|tmr|tomm?orow|"
                         r"mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?)\b", re.I)


def _year_for(month: int, day: int, base: datetime) -> int:
    """Pick the year that puts month/day closest to (and preferably after) the note date."""
    y = base.year
    try:
        cand = date(y, month, day)
    except ValueError:
        return y
    if (base.date() - cand).days > 30:
        return y + 1
    return y


def _to_24h(h: int, mer: Optional[str]) -> int:
    if not mer:
        return h
    mer = mer.lower().replace(".", "")
    if mer == "pm" and h != 12:
        return h + 12
    if mer == "am" and h == 12:
        return 0
    return h


def parse_callback_time(text: str, written_at: datetime) -> Optional[datetime]:
    """
    Find a callback/meeting start time in free text (note body or OCR output).
    Relative words are resolved against `written_at`; all times are Central.
    Returns an aware datetime (CT) or None if no reliable time is present.
    """
    if not text:
        return None
    t = " ".join(text.split())
    base = to_ct(written_at)

    # 1) Calendar-style: "Tuesday, September 29 · 12:00 – 1:00pm"
    m = _RE_CAL.search(t)
    if m:
        mon = _month(m.group(1))
        if mon:
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else _year_for(mon, day, base)
            sh, sm = int(m.group(4)), int(m.group(5) or 0)
            smer = m.group(6)
            eh, emer = int(m.group(7)), m.group(9)
            if not smer:
                # infer start meridiem from end ("12:00 – 1:00pm" → pm, "11:00 – 12:00pm" → am)
                smer = "pm" if _to_24h(sh, "pm") <= _to_24h(eh, emer) else "am"
            try:
                return TZ.localize(datetime(year, mon, day, _to_24h(sh, smer), sm))
            except ValueError:
                pass

    # 2) Relative: "callback in 2 hours"
    m = _RE_RELATIVE.search(t)
    if m:
        qty = float(m.group(1))
        unit = m.group(2).lower()
        delta = timedelta(hours=qty) if unit.startswith("h") else timedelta(minutes=qty)
        return base + delta

    # 3) Day + time
    tm = _RE_TIME.search(t)
    hour = minute = None
    if tm:
        hour, minute = _to_24h(int(tm.group(1)), tm.group(3)), int(tm.group(2) or 0)
    elif _RE_NOON.search(t):
        hour, minute = 12, 0
    if hour is None or not (0 <= hour <= 23):
        return None  # a day without a time isn't reliable enough

    target: Optional[date] = None
    md = next((x for x in _RE_MONTH_DAY.finditer(t) if _month(x.group(1))), None)
    if md:
        mon, day = _month(md.group(1)), int(md.group(2))
        year = int(md.group(3)) if md.group(3) else _year_for(mon, day, base)
        try:
            target = date(year, mon, day)
        except ValueError:
            target = None
    if target is None:
        nd = _RE_NUM_DATE.search(t)
        if nd:
            mon, day = int(nd.group(1)), int(nd.group(2))
            year = int(nd.group(3)) if nd.group(3) else _year_for(mon, day, base)
            if year < 100:
                year += 2000
            try:
                target = date(year, mon, day)
            except ValueError:
                target = None
    if target is None:
        dw = _RE_DAYWORD.search(t)
        if dw:
            w = dw.group(1).lower()
            if w in ("today", "tonight"):
                target = base.date()
            elif w.startswith("tm") or w.startswith("tom"):
                target = base.date() + timedelta(days=1)
            else:
                wd = _WEEKDAYS[w[:3]]
                ahead = (wd - base.weekday()) % 7 or 7
                target = base.date() + timedelta(days=ahead)
    if target is None:
        # time only → that time today, or tomorrow if it has already passed
        target = base.date()
        if TZ.localize(datetime.combine(target, time(hour, minute))) <= base:
            target += timedelta(days=1)
    return TZ.localize(datetime.combine(target, time(hour, minute)))


# ─── Rule evaluation ──────────────────────────────────────────────────────────

def evaluate_ticket(ticket: dict, details: dict, now: datetime) -> dict:
    """
    ticket  : raw Zoho ticket (status, createdTime, assigneeId, ...)
    details : {
        "agent_replies":   [datetime, ...]   outgoing threads by agents
        "customer_msgs":   [datetime, ...]   incoming threads from the customer
        "first_thread_in": bool|None         True if the ticket was opened by the customer
        "notes":           [{"time": dt, "text": str, "image_text": str|None}, ...]  private notes by agents
        "assigned_at":     datetime|None     when the current assignee got the ticket
        "resumed_at":      datetime|None     last time it left "Pending customer"
    }
    Returns {"rule", "state", "hours", "clock_start", "detail"} where state is one of
    "breach", "at_risk", "ok", "paused", "scheduled", "unclear".
    """
    status = (ticket.get("status") or "").strip().lower()
    created = parse_dt(ticket.get("createdTime"))
    replies = sorted(d for d in details.get("agent_replies", []) if d)
    notes = sorted((n for n in details.get("notes", []) if n.get("time")), key=lambda n: n["time"])
    actions = sorted(replies + [n["time"] for n in notes])

    def result(rule, state, hours=0.0, clock_start=None, detail=""):
        return {"rule": rule, "state": state, "hours": round(hours, 1),
                "clock_start": clock_start.isoformat() if clock_start else None, "detail": detail}

    if status in PAUSED_STATUSES:
        return result("paused", "paused", detail="Pending customer — clock paused")

    # Rule 4 — Pending Meeting
    if status in MEETING_STATUSES:
        callback, source, source_note = None, None, None
        for n in reversed(notes):
            cb = parse_callback_time(n.get("text") or "", n["time"])
            src = "note"
            if cb is None and n.get("image_text"):
                cb = parse_callback_time(n["image_text"], n["time"])
                src = "screenshot"
            if cb is not None:
                callback, source, source_note = cb, src, n
                break
        if callback is None:
            return result("callback", "unclear", detail="Pending Meeting but no callback time found in private notes")
        deadline = callback + timedelta(hours=CALLBACK_GRACE_HOURS)
        # follow-up = a reply, or a note other than the one that set the callback
        followed_up = any(a > callback for a in replies) or any(
            n["time"] > callback and n is not source_note for n in notes)
        if followed_up:
            return result("callback", "ok", clock_start=callback, detail=f"Note added after callback ({source})")
        if now < callback:
            return result("callback", "scheduled", clock_start=callback,
                          detail=f"Callback {to_ct(callback):%a %b %d %I:%M %p} CT ({source})")
        over = (now - callback).total_seconds() / 3600
        if now >= deadline:
            return result("callback", "breach", over, callback,
                          f"No note {CALLBACK_GRACE_HOURS:g}h after callback at {to_ct(callback):%a %b %d %I:%M %p} CT ({source})")
        return result("callback", "at_risk", over, callback,
                      f"Callback at {to_ct(callback):%I:%M %p} CT — note due by {to_ct(deadline):%I:%M %p}")

    # Rule 1 — First response (customer-raised, no agent reply yet)
    if details.get("first_thread_in") is not None:
        customer_raised = bool(details["first_thread_in"])
    else:
        customer_raised = bool(details.get("customer_msgs"))
    if customer_raised and not replies and created:
        start = next_business_open(created)
        hrs = business_hours_between(start, now)
        if hrs >= FIRST_RESPONSE_HOURS:
            return result("first_response", "breach", hrs, start,
                          f"No first response after {hrs:.1f} business hours")

    # Rules 2 & 3 — Agent inactivity (assigned tickets)
    if not ticket.get("assigneeId"):
        return result("unassigned", "ok", detail="Not assigned to an agent")

    candidates = [details.get("assigned_at"), details.get("resumed_at")]
    candidates += [a for a in actions]
    candidates = [c for c in candidates if c]
    start_raw = max(candidates) if candidates else created
    if not start_raw:
        return result("inactivity", "ok", detail="No timestamps")
    start = next_business_open(start_raw)
    biz = business_hours_between(start, now)
    wk = weekday_hours_between(start, now)
    crossed = business_date(now) > business_date(start)

    if wk > BREACH_WEEKDAY_HOURS and crossed:
        return result("carried_over", "breach", wk, start,
                      f"No action for {wk:.0f} weekday hours (since {to_ct(start):%a %b %d %I:%M %p} CT)")
    if biz >= AT_RISK_HOURS:
        return result("inactivity", "at_risk", biz, start,
                      f"No action for {biz:.1f} business hours")
    return result("inactivity", "ok", biz, start)
