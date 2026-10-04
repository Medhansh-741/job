from fastapi import FastAPI, Depends, File, UploadFile, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from app.core.auth import get_current_user, AuthenticatedUser
from app.services.document_validator import validate_document
from app.services.storage import (
    upload_resume_to_storage,
    delete_resume_from_storage,
    create_signed_download_url,
)
from app.core.db import (
    get_active_resume_record,
    save_active_resume_record,
    delete_active_resume_record,
)

app = FastAPI(title="Job Matcher API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "job-matcher-api"}

@app.get("/me")
def get_me(user: AuthenticatedUser = Depends(get_current_user)):
    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
        "authenticated": True,
    }

@app.get("/resumes/active")
async def get_active_resume(user: AuthenticatedUser = Depends(get_current_user)):
    """Fetch user's current active resume with a signed download URL."""
    record = get_active_resume_record(user.id)
    if not record:
        return {"active": None}

    download_url = await create_signed_download_url(record["storage_path"])

    return {
        "active": {
            "id": str(record["id"]),
            "filename": record["filename"],
            "file_size": record["file_size"],
            "mime_type": record["mime_type"],
            "download_url": download_url,
            "created_at": record["created_at"].isoformat() if record.get("created_at") else None,
            "updated_at": record["updated_at"].isoformat() if record.get("updated_at") else None,
        }
    }

@app.delete("/resumes/active")
async def delete_active_resume(user: AuthenticatedUser = Depends(get_current_user)):
    """
    Purges user's single active resume from DB and cloud storage.
    Cascades to delete matches and profile so dashboard resets to empty state.
    """
    old_storage_path = delete_active_resume_record(user.id)
    if old_storage_path:
        await delete_resume_from_storage(old_storage_path)

    return {
        "success": True,
        "message": "Active resume and associated matches purged successfully",
    }

@app.post("/resumes/upload")
async def upload_resume(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Uploads a new resume.
    If the user already has an active resume, replaces it and cleans up the previous file.
    """
    content = await file.read()

    # 1. 5-layer document validation (size, extension, magic bytes, zip bomb, readability)
    original_name = file.filename or "resume.pdf"
    doc = validate_document(filename=original_name, content=content)

    # 2. Persist to isolated user folder in Supabase Private Storage
    storage_path = await upload_resume_to_storage(
        user_id=user.id,
        safe_filename=doc.safe_filename,
        content=doc.raw_bytes,
        content_type=doc.content_type,
    )

    # 3. Atomically save as active resume in DB, retrieving previous storage path if any
    new_record, old_storage_path = save_active_resume_record(
        user_id=user.id,
        filename=original_name,
        storage_path=storage_path,
        file_size=len(doc.raw_bytes),
        mime_type=doc.content_type,
        raw_text=doc.extracted_text,
    )

    # 4. If replacing an existing resume, purge old file from storage
    if old_storage_path and old_storage_path != storage_path:
        await delete_resume_from_storage(old_storage_path)

    return {
        "success": True,
        "active": {
            "id": str(new_record["id"]),
            "filename": new_record["filename"],
            "file_size": new_record["file_size"],
            "storage_path": storage_path,
        },
        "characters_extracted": len(doc.extracted_text),
    }
