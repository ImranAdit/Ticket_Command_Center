from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
import os

from dotenv import load_dotenv
load_dotenv()

from routers import zoho, sync, actions
from logic.business_hours import classify_ticket, calculateBusinessIdle
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ─── Scheduler setup ─────────────────────────────────────────────────────────
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services.zoho_fetcher import run_sync

scheduler = AsyncIOScheduler()


async def _initial_sync():
    """Run first sync 5 seconds after startup."""
    await asyncio.sleep(5)
    logger.info("Running initial Zoho sync on startup...")
    await run_sync()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: kick off scheduler and initial sync. Shutdown: stop scheduler."""
    sync_interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "15"))
    scheduler.add_job(run_sync, "interval", minutes=sync_interval, id="zoho_sync",
                      misfire_grace_time=60)
    scheduler.start()
    logger.info(f"Scheduler started — Zoho sync every {sync_interval} min")

    # Fire initial sync in background (don't block startup)
    asyncio.create_task(_initial_sync())

    yield

    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Adit Ticket Command Center — Backend",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(zoho.router,    prefix="/api/zoho",    tags=["zoho"])
app.include_router(sync.router,    prefix="/api/sync",    tags=["sync"])
app.include_router(actions.router, prefix="/api/actions", tags=["actions"])


# ─── Legacy classify endpoint (kept for backward compat) ──────────────────────
class TicketInput(BaseModel):
    id: str
    status: str
    created_at: datetime
    modified_at: Optional[datetime] = None

class ClassifyRequest(BaseModel):
    tickets: List[TicketInput]

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Adit TCC Backend v2 — SLA Breach Engine active"}

@app.post("/api/logic/classify")
def classify_tickets(req: ClassifyRequest):
    results = []
    now = datetime.utcnow()
    for t in req.tickets:
        metrics = classify_ticket(t.model_dump(), now)
        results.append({"id": t.id, "metrics": metrics})
    return {"results": results}
