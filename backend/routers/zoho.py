from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

class ZohoRequest(BaseModel):
    org_id: str
    dc: str
    token: str

@router.post("/fetch-summary")
async def fetch_zoho_summary(req: ZohoRequest):
    """
    Proxies request to Zoho Desk to prevent exposing secrets if we ever add them.
    Currently, uses the token provided by the user for session.
    """
    url = f"https://desk.zoho.{req.dc}/api/v1/tickets"
    headers = {
        "orgId": req.org_id,
        "Authorization": f"Zoho-oauthtoken {req.token}"
    }

    async with httpx.AsyncClient() as client:
        try:
            # We fetch a subset of fields just to get the summary stats
            response = await client.get(
                url, 
                headers=headers,
                params={"limit": 100}
            )
            response.raise_for_status()
            data = response.json()
            return data
            
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=f"Zoho API Error: {exc.response.text}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
