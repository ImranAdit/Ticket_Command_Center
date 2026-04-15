from datetime import datetime, timedelta
import pytz

# Business hours are 07:00 to 19:00 CST
BUSINESS_START = 7
BUSINESS_END = 19
BUSINESS_HOURS_PER_DAY = BUSINESS_END - BUSINESS_START

# Define CST timezone
CST_TZ = pytz.timezone('America/Chicago')

def to_cst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return CST_TZ.localize(dt)
    return dt.astimezone(CST_TZ)

def calculateBusinessIdle(start_time: datetime, end_time: datetime) -> float:
    """
    Returns the total business hours between start_time and end_time.
    Excludes weekends and hours outside 7:00 AM - 7:00 PM CST.
    """
    start_cst = to_cst(start_time)
    end_cst = to_cst(end_time)
    
    if end_cst <= start_cst:
        return 0.0

    total_hours = 0.0
    cursor = start_cst

    while cursor < end_cst:
        # Check if weekday (0=Monday, 6=Sunday)
        if cursor.weekday() < 5:
            day_start = cursor.replace(hour=BUSINESS_START, minute=0, second=0, microsecond=0)
            day_end = cursor.replace(hour=BUSINESS_END, minute=0, second=0, microsecond=0)
            
            # Start and End bounds for this day
            s = max(cursor, day_start)
            e = min(end_cst, day_end)
            
            if e > s:
                total_hours += (e - s).total_seconds() / 3600.0
        
        # Move cursor to start of next day
        next_day = cursor + timedelta(days=1)
        cursor = next_day.replace(hour=BUSINESS_START, minute=0, second=0, microsecond=0)

    return total_hours

def classify_ticket(ticket: dict, now: datetime = None) -> dict:
    """
    Aging Modules implementation:
    Module 1: General bucketing (24h, 2d, 3d, 4d+)
    Module 2: Dev-Watch (Status == "Pending Development", IdleTime > 3 Business Days)
    Module 3: Flash Response (CreatedDate == Today, Age > 4 Business Hours with no response)
    """
    if now is None:
        now = datetime.utcnow()
    now_cst = to_cst(now)

    created_at = ticket.get("created_at")
    modified_at = ticket.get("modified_at") or created_at
    status = ticket.get("status", "").lower()

    if not created_at:
        return {"error": "Missing created_at"}

    created_cst = to_cst(created_at)
    
    biz_hours_idle = calculateBusinessIdle(modified_at, now_cst)
    biz_hrs_create = calculateBusinessIdle(created_at, now_cst)
    
    biz_days_idle = biz_hours_idle / BUSINESS_HOURS_PER_DAY

    is_pending_dev = "pending dev" in status or "development" in status
    is_today = created_cst.date() == now_cst.date()

    alert_class = "normal"
    
    # Module 3: Flash Response
    if is_today and biz_hrs_create >= 4 and biz_hours_idle >= 4:
        alert_class = "flash"
    # Module 2: Dev-Watch
    elif is_pending_dev and biz_days_idle > 3:
        alert_class = "dev_overdue"
    # Module 1: General Bucketing
    elif biz_days_idle >= 3:
        alert_class = "72h+"
    elif biz_hours_idle >= 48:
        alert_class = "48h+"
    elif biz_hours_idle >= 24:
        alert_class = "24h+"

    return {
        "biz_hours_idle": round(biz_hours_idle, 2),
        "biz_days_idle": round(biz_days_idle, 2),
        "alert_class": alert_class,
        "is_today": is_today,
        "is_pending_dev": is_pending_dev
    }
