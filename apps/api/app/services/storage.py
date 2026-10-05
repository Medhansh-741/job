import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import httpx
from fastapi import HTTPException, status

ROOT_ENV = Path(__file__).resolve().parent.parent.parent.parent.parent / ".env"
if ROOT_ENV.exists():
    load_dotenv(ROOT_ENV)
else:
    load_dotenv()

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
if not SUPABASE_URL:
    # No default on purpose: a silent fallback would send resumes to the wrong project.
    raise RuntimeError("SUPABASE_URL is not set. Add it to .env (see .env.example).")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")


def _get_headers(content_type: Optional[str] = None) -> dict:
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: SUPABASE_SERVICE_ROLE_KEY not configured",
        )
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


async def upload_resume_to_storage(
    user_id: str, safe_filename: str, content: bytes, content_type: str
) -> str:
    """Upload validated resume bytes to private Supabase resumes bucket."""
    storage_path = f"{user_id}/{safe_filename}"
    url = f"{SUPABASE_URL}/storage/v1/object/resumes/{storage_path}"

    headers = _get_headers(content_type)
    headers["x-upsert"] = "true"

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, headers=headers, content=content)

        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to persist document to storage: {response.text}",
            )

    return storage_path


async def delete_resume_from_storage(storage_path: str) -> bool:
    """Delete a resume file from private storage bucket."""
    if not storage_path:
        return False

    url = f"{SUPABASE_URL}/storage/v1/object/resumes/{storage_path}"
    headers = _get_headers()

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(url, headers=headers)
        # 200 or 404 (already gone) are acceptable
        return response.status_code in (200, 204, 404)


async def create_signed_download_url(storage_path: str, expires_in: int = 3600) -> Optional[str]:
    """Generate a time-limited signed download URL for private resume."""
    if not storage_path:
        return None

    url = f"{SUPABASE_URL}/storage/v1/object/sign/resumes/{storage_path}"
    headers = _get_headers("application/json")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, headers=headers, json={"expiresIn": expires_in})

        if response.status_code == 200:
            data = response.json()
            signed_url_path = data.get("signedURL")
            if signed_url_path:
                return f"{SUPABASE_URL}/storage/v1{signed_url_path}"

        return None
