"""
Actions Router — quick actions on tickets via Zoho Desk API.
Supports: add comment, reassign, escalate (add tag).
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import httpx
from logic.zoho_auth import get_access_token, is_configured
from services.zoho_fetcher import _api_base, _headers

router = APIRouter()
logger = logging.getLogger(__name__)


class CommentRequest(BaseModel):
    ticket_id: str
    content: str
    is_public: bool = False


class AssignRequest(BaseModel):
    ticket_id: str
    agent_id: str


class EscalateRequest(BaseModel):
    ticket_id: str
    note: Optional[str] = "Escalated — SLA breach with no action"


def _check_configured():
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail="Zoho credentials not configured. Add them to backend/.env"
        )


@router.post("/comment")
async def add_comment(req: CommentRequest):
    """Add an internal comment (or public reply) to a ticket."""
    _check_configured()
    url = f"{_api_base()}/api/v1/tickets/{req.ticket_id}/comments"
    payload = {
        "content": req.content,
        "contentType": "html",
        "isPublic": req.is_public,
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=_headers(), timeout=15)
            resp.raise_for_status()
            return {"status": "ok", "comment": resp.json()}
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Zoho API error: {e.response.text[:200]}")


@router.post("/assign")
async def assign_ticket(req: AssignRequest):
    """Reassign ticket to a different agent."""
    _check_configured()
    url = f"{_api_base()}/api/v1/tickets/{req.ticket_id}"
    payload = {"assigneeId": req.agent_id}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.patch(url, json=payload, headers=_headers(), timeout=15)
            resp.raise_for_status()
            return {"status": "ok", "ticket": resp.json()}
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Zoho API error: {e.response.text[:200]}")


@router.post("/escalate")
async def escalate_ticket(req: EscalateRequest):
    """Escalate a ticket by adding 'Escalated' tag and an internal note."""
    _check_configured()
    base = _api_base()
    hdrs = _headers()

    async with httpx.AsyncClient() as client:
        errors = []

        # 1. Add internal comment/note
        comment_url = f"{base}/api/v1/tickets/{req.ticket_id}/comments"
        try:
            cr = await client.post(comment_url,
                                   json={"content": req.note, "contentType": "plainText",
                                         "isPublic": False},
                                   headers=hdrs, timeout=15)
            cr.raise_for_status()
        except httpx.HTTPStatusError as e:
            errors.append(f"comment: {e.response.status_code}")

        # 2. Associate 'Escalated' tag
        tag_url = f"{base}/api/v1/tickets/{req.ticket_id}/tags"
        try:
            tr = await client.post(tag_url, json={"tags": ["Escalated"]},
                                   headers=hdrs, timeout=15)
            tr.raise_for_status()
        except httpx.HTTPStatusError as e:
            errors.append(f"tag: {e.response.status_code}")

        if errors:
            return {"status": "partial", "errors": errors, "ticket_id": req.ticket_id}
        return {"status": "ok", "ticket_id": req.ticket_id, "message": "Ticket escalated"}
