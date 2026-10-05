from typing import Optional
from fastapi import FastAPI, Depends, File, UploadFile, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from app.core.auth import get_current_user, AuthenticatedUser
from app.services.document_validator import validate_document
from app.services.resume_parser import parse_resume
from app.services.profile_enricher import enrich_candidate_profile
from app.services.embedding_service import (
    build_candidate_embedding_payload,
    resolve_candidate_embedding,
)
from app.services.storage import (
    upload_resume_to_storage,
    delete_resume_from_storage,
    create_signed_download_url,
)
from app.core.db import (
    get_active_resume_record,
    save_active_resume_record,
    delete_active_resume_record,
    save_candidate_profile,
    get_candidate_profile,
)
from app.core.worker import matching_worker, lifespan
from app.services.matching_engine import execute_matching_funnel, get_persisted_matches

app = FastAPI(title="Job Matcher API", version="0.1.0", lifespan=lifespan)

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

@app.get("/profiles/me")
def get_my_profile(user: AuthenticatedUser = Depends(get_current_user)):
    """Fetch user's parsed candidate profile from Supabase."""
    profile = get_candidate_profile(user.id)
    return {"profile": profile}

@app.post("/resumes/upload")
async def upload_resume(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Uploads a new resume.
    1. Validates document (magic bytes, size, format).
    2. Uploads to Supabase Private Storage.
    3. Saves active resume record in DB.
    4. Deterministically parses sections, skills, experience, and stores profile.
    5. Checks content hash cache: if identical resume & matches exist, bypasses worker.
    6. If new or modified, enqueues background matching pass through in-process MatchingWorker.
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

    # 5. Deterministic Resume Parsing & Profile Structuring
    parsed = parse_resume(
        content=doc.raw_bytes,
        mime_type=doc.content_type,
        filename=original_name,
    )

    # 5.1 Systematic LLM Profile Understanding & Target Role Inference if missing
    if not parsed.headline or not parsed.preferred_roles:
        enriched = await enrich_candidate_profile(
            markdown=parsed.markdown,
            skills=parsed.skills,
        )
        if not parsed.headline:
            parsed.headline = enriched.get("headline")
        if not parsed.preferred_roles:
            parsed.preferred_roles = enriched.get("preferred_roles", [])

    # 6. Candidate Embedding Synthesis & Content Hash Cache Check
    existing_profile = get_candidate_profile(user.id)
    existing_hash = existing_profile.get("content_hash") if existing_profile else None
    existing_emb = existing_profile.get("embedding") if existing_profile else None

    payload_text = build_candidate_embedding_payload(
        headline=parsed.headline,
        preferred_roles=parsed.preferred_roles,
        skills=parsed.skills,
        full_time_experience_years=parsed.full_time_experience_years,
        internship_months=parsed.internship_months,
    )

    embedding, content_hash, is_cache_hit = resolve_candidate_embedding(
        payload_text=payload_text,
        existing_hash=existing_hash,
        existing_embedding=existing_emb,
    )

    profile_record = save_candidate_profile(
        user_id=user.id,
        headline=parsed.headline,
        skills=parsed.skills,
        experience_years=parsed.full_time_experience_years,
        preferred_roles=parsed.preferred_roles,
        raw_json={
            "detected_headings": parsed.detected_headings,
            "sections": parsed.sections,
            "markdown": parsed.markdown,
            "full_time_experience_years": parsed.full_time_experience_years,
            "internship_months": parsed.internship_months,
            "is_fresher": parsed.is_fresher,
        },
        embedding=embedding,
        content_hash=content_hash,
    )

    # 7. Match Lifecycle Contract:
    # If identical content hash AND user already has computed matches in DB -> bypass worker (0ms CPU, 0 tokens)
    # If modified resume or matches missing -> enqueue background task with concurrency shield
    existing_matches = get_persisted_matches(user.id, limit=1)
    if is_cache_hit and existing_matches:
        # Cache hit bypass: keep existing matches intact, 0 API tokens consumed
        pass
    else:
        await matching_worker.enqueue(user_id=user.id, region="india", limit=15)

    return {
        "success": True,
        "active": {
            "id": str(new_record["id"]),
            "filename": new_record["filename"],
            "file_size": new_record["file_size"],
            "storage_path": storage_path,
        },
        "profile": {
            "headline": parsed.headline,
            "skills": parsed.skills,
            "experience_years": parsed.full_time_experience_years,
            "full_time_experience_years": parsed.full_time_experience_years,
            "internship_months": parsed.internship_months,
            "is_fresher": parsed.is_fresher,
            "preferred_roles": parsed.preferred_roles,
            "sections_count": len(parsed.sections),
            "content_hash": content_hash,
            "is_cache_hit": is_cache_hit,
            "has_embedding": True,
        },
        "characters_extracted": len(doc.extracted_text),
    }


@app.get("/matches")
async def get_matches(
    region: Optional[str] = Query("india", description="Target region: india, us, remote, or all"),
    limit: Optional[int] = Query(15, ge=1, le=100, description="Max matches to return"),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns user's top matches.
    Fast path: returns persisted matches from public.matches (< 2ms).
    Cold path: executes matching funnel if public.matches is empty.
    """
    persisted = get_persisted_matches(user.id, limit=limit or 15)
    if persisted:
        target_reg = region or "india"
        if target_reg == "all":
            filtered = persisted
        elif target_reg == "india":
            filtered = [m for m in persisted if m.get("region") in ("india", "remote")]
        elif target_reg == "us":
            filtered = [m for m in persisted if m.get("region") in ("us", "remote")]
        elif target_reg == "remote":
            filtered = [m for m in persisted if m.get("region") == "remote"]
        else:
            filtered = [m for m in persisted if m.get("region") == target_reg]

        if filtered:
            return {
                "matches": filtered[:limit],
                "total_evaluated": len(persisted),
                "live_fallback_triggered": False,
                "strong_matches_count": sum(1 for m in filtered if m["match_score"] >= 60),
            }

    # Cold path: compute and persist
    result = await execute_matching_funnel(
        user_id=user.id,
        target_region=region or "india",
        limit=limit or 25,
    )
    return result
