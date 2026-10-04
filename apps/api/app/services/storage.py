import os
from pathlib import Path
from dotenv import load_dotenv
import httpx
from fastapi import HTTPException, status

ROOT_ENV = Path(__file__).resolve().parent.parent.parent.parent.parent / ".env"
if ROOT_ENV.exists():
    load_dotenv(ROOT_ENV)
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://uefisekynsvefbcvaivb.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")


async def upload_resume_to_storage(
    user_id: str, safe_filename: str, content: bytes, content_type: str
) -> str:
    """Upload validated resume bytes to private Supabase resumes bucket."""
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: SUPABASE_SERVICE_ROLE_KEY not configured",
        )

    storage_path = f"{user_id}/{safe_filename}"
    url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/resumes/{storage_path}"

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": content_type,
        "x-upsert": "false",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, headers=headers, content=content)

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to persist document to storage: {response.text}",
            )

    return storage_path
