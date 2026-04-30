from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
import asyncio
import logging
import os

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import your local logic and routers
# Note: Ensure these files exist in your 'backend' folder
from routers import zoho, sync, actions
from logic.business_hours import classify_ticket
from services.zoho_fetcher import run_sync
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─── Logging Setup ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ─── Scheduler Setup ────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()

async def _initial_sync():
    """Run first sync 5 seconds after startup."""
    await asyncio.sleep(5)
    logger.info("Running initial Zoho sync on startup...")
    try:
        await run_sync()
    except Exception as e:
        logger.error(f"Initial sync failed: {e}")

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

# ─── App Configuration ──────────────────────────────────────────────────────
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

# ─── API Routers ────────────────────────────────────────────────────────────
app.include_router(zoho.router,    prefix="/api/zoho",    tags=["zoho"])
app.include_router(sync.router,    prefix="/api/sync",    tags=["sync"])
app.include_router(actions.router, prefix="/api/actions", tags=["actions"])

# ─── Models ─────────────────────────────────────────────────────────────────
class TicketInput(BaseModel):
    id: str
    status: str
    created_at: datetime
    modified_at: Optional[datetime] = None

class ClassifyRequest(BaseModel):
    tickets: List[TicketInput]

# ─── Endpoints ──────────────────────────────────────────────────────────────
@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "2.0.0", "message": "SLA Breach Engine active"}

@app.post("/api/logic/classify")
def classify_tickets(req: ClassifyRequest):
    results = []
    now = datetime.utcnow()
    for t in req.tickets:
        metrics = classify_ticket(t.model_dump(), now)
        results.append({"id": t.id, "metrics": metrics})
    return {"results": results}

# ─── Static Files & SPA Handling ───────────────────────────────────────────
# This section handles serving the React/Vite frontend from the 'static' folder
STATIC_PATH = "static"

if os.path.exists(STATIC_PATH):
    # Mount the static directory for direct asset access (CSS, JS, Images)
    app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # 1. Ignore API calls so they can fall through to routers or return 404 correctly
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
            
        # 2. Check if the requested path is an actual file (like /favicon.ico)
        potential_file = os.path.join(STATIC_PATH, full_path)
        if os.path.isfile(potential_file):
            return FileResponse(potential_file)
            
        # 3. Otherwise, serve index.html for all other routes (SPA client-side routing)
        index_file = os.path.join(STATIC_PATH, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
            
        raise HTTPException(status_code=404, detail="Index file not found")
else:
    logger.warning("⚠️ 'static' directory not found. Frontend will not be served.")
    @app.get("/")
    def root_warning():
        return {
            "status": "warning", 
            "message": "Backend is running, but frontend files are missing. Check Docker build."
        }
