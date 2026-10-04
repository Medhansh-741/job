from fastapi import FastAPI, Depends, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from app.core.auth import get_current_user, AuthenticatedUser
from app.services.document_validator import validate_document
from app.services.storage import upload_resume_to_storage

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

@app.post("/resumes/upload")
async def upload_resume(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    content = await file.read()

    # 1. Complete 5-layer document validation (size, extension, magic bytes, zip bomb, readability)
    doc = validate_document(filename=file.filename or "resume.pdf", content=content)

    # 2. Persist to isolated user folder in Supabase Private Storage
    storage_path = await upload_resume_to_storage(
        user_id=user.id,
        safe_filename=doc.safe_filename,
        content=doc.raw_bytes,
        content_type=doc.content_type,
    )

    return {
        "success": True,
        "resume_id": doc.safe_filename,
        "storage_path": storage_path,
        "characters_extracted": len(doc.extracted_text),
        "preview": doc.extracted_text[:200],
    }
