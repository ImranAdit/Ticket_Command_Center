import os
import httpx
from dotenv import load_dotenv

load_dotenv()

def probe():
    client_id = os.getenv("ZOHO_CLIENT_ID")
    client_secret = os.getenv("ZOHO_CLIENT_SECRET")
    token = os.getenv("ZOHO_REFRESH_TOKEN")
    
    dcs = ["com", "eu", "in", "au", "jp"]
    
    for dc in dcs:
        url = f"https://accounts.zoho.{dc}/oauth/v2/token"
        print(f"\n--- Checking DC: {dc} ---")
        
        # Try as refresh_token
        try:
            r = httpx.post(url, data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": token
            })
            print(f"Refreh Token Attempt: {r.status_code} - {r.json()}")
        except Exception as e:
            print(f"Refreh Error: {e}")

        # Try as authorization_code (in case user pasted the 10-min code)
        try:
            r = httpx.post(url, data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": token
            })
            print(f"Auth Code Attempt: {r.status_code} - {r.json()}")
            if r.status_code == 200 and "refresh_token" in r.json():
                print(">>> SUCCESS! It was an authorization code. New Refresh Token obtained.")
                return r.json()["refresh_token"]
        except Exception as e:
            print(f"Auth Code Error: {e}")

if __name__ == "__main__":
    new_token = probe()
    if new_token:
        print(f"\nUPDATING .ENV with new token...")
        # (I will do this part manually or with tool)
