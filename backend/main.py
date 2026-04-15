from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import zoho
from logic.business_hours import classify_ticket, calculateBusinessIdle
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

app = FastAPI(title="Adit Ticket Command Center - Backend")

# Allow all origins for simplicity in development, restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.include_router(zoho.router, prefix="/api/zoho", tags=["zoho"])

class TicketInput(BaseModel):
    id: str
    status: str
    created_at: datetime
    modified_at: Optional[datetime] = None

class ClassifyRequest(BaseModel):
    tickets: List[TicketInput]

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Adit Backend Runtime is active"}

@app.post("/api/logic/classify")
def classify_tickets(req: ClassifyRequest):
    """
    Takes a list of tickets and returns them with their calculated business hour metrics
    and alert classes.
    """
    results = []
    now = datetime.utcnow()
    for t in req.tickets:
        metrics = classify_ticket(t.model_dump(), now)
        results.append({
            "id": t.id,
            "metrics": metrics
        })
    return {"results": results}
