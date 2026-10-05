import asyncio
import os
import hashlib
import time
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
    clear_user_matches,
    candidate_ready,
)
from app.core.worker import matching_worker, lifespan
from app.core.task_tracker import task_tracker
from app.services.matching_engine import get_persisted_matches, DISPLAY_LIMIT

# After a finished run, GET /matches will not enqueue another one for this long (stops refresh loops)
ENQUEUE_COOLDOWN_SECONDS = 60.0

# Browsers reach the API only through the Next.js proxy (server-to-server, no CORS), so the default allows just
# local dev origins. Set CORS_ORIGINS (comma-separated) if a browser app must call the API directly.
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if o.strip()
]

_background_tasks: set = set()


def _fire_and_forget(coro) -> None:
    """Runs a cleanup coroutine in the background; failures are swallowed (best-effort cleanup)."""
    async def _quiet():
        try:
            await coro
        except Exception:
            pass
    task = asyncio.ensure_future(_quiet())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


app = FastAPI(title="Job Matcher API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,   # the API uses Bearer tokens, never cookies
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
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
    Cascades to delete matches, profile and cached LLM evaluations so dashboard resets to empty state.
    """
    matching_worker.cancel_retry(user.id)
    old_storage_path = await asyncio.to_thread(delete_active_resume_record, user.id)
    task_tracker.clear(user.id)
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
    task_tracker.set_progress(
        user.id,
        status="processing",
        progress=10,
        step_label="Validating document integrity & reading content...",
    )
    content = await file.read()

    # 1. 5-layer document validation (size, extension, magic bytes, zip bomb, readability) - CPU, off the loop
    original_name = file.filename or "resume.pdf"
    doc = await asyncio.to_thread(validate_document, filename=original_name, content=content)

    task_tracker.set_progress(
        user.id,
        status="processing",
        progress=25,
        step_label="Parsing technical skills & structuring profile...",
    )

    # 2+5. Storage upload (network) and deterministic parsing (CPU) are independent: run them concurrently
    upload_task = asyncio.ensure_future(upload_resume_to_storage(
        user_id=user.id,
        safe_filename=doc.safe_filename,
        content=doc.raw_bytes,
        content_type=doc.content_type,
    ))
    profile_task = asyncio.ensure_future(asyncio.to_thread(get_candidate_profile, user.id))  # independent of parsing
    try:
        parsed = await asyncio.to_thread(
            parse_resume,
            content=doc.raw_bytes,
            mime_type=doc.content_type,
            filename=original_name,
        )
    except Exception:
        # Parsing failed: do not leave an orphaned file in storage
        try:
            _fire_and_forget(delete_resume_from_storage(await upload_task))
        except Exception:
            pass
        raise
    existing_profile = await profile_task
    existing_raw = (existing_profile or {}).get("raw_json") or {}
    markdown_hash = hashlib.sha256((parsed.markdown or "").encode("utf-8")).hexdigest()

    # 5.1 LLM Profile Understanding & Target Role Inference, only when needed.
    # Identical resume text with a previously LLM-derived headline/roles -> reuse them (0 tokens).
    enriched_by_llm = True
    if not parsed.headline or not parsed.preferred_roles:
        can_reuse = bool(
            existing_profile
            and existing_raw.get("markdown_hash") == markdown_hash
            and existing_raw.get("enriched_by_llm")
            and existing_profile.get("headline")
            and existing_profile.get("preferred_roles")
        )
        if can_reuse:
            parsed.headline = parsed.headline or existing_profile["headline"]
            parsed.preferred_roles = parsed.preferred_roles or existing_profile["preferred_roles"]
        else:
            task_tracker.set_progress(
                user.id,
                status="processing",
                progress=38,
                step_label="Inferring engineering domain & target roles via LLM...",
            )
            enriched = await enrich_candidate_profile(
                markdown=parsed.markdown,
                skills=parsed.skills,
            )
            enriched_by_llm = enriched.get("source") == "llm"
            if not parsed.headline:
                parsed.headline = enriched.get("headline")
            if not parsed.preferred_roles:
                parsed.preferred_roles = enriched.get("preferred_roles", [])

    # 6. Candidate Embedding Synthesis & Content Hash Cache Check
    existing_hash = existing_profile.get("content_hash") if existing_profile else None
    existing_emb = existing_profile.get("embedding") if existing_profile else None

    payload_text = build_candidate_embedding_payload(
        headline=parsed.headline,
        preferred_roles=parsed.preferred_roles,
        skills=parsed.skills,
        full_time_experience_years=parsed.full_time_experience_years,
        internship_months=parsed.internship_months,
    )

    embedding, content_hash, is_cache_hit = await asyncio.to_thread(
        resolve_candidate_embedding,
        payload_text,
        existing_hash,
        existing_emb,
    )

    await asyncio.to_thread(
        save_candidate_profile,
        user_id=user.id,
        headline=parsed.headline,
        skills=parsed.skills,
        experience_years=parsed.full_time_experience_years,
        preferred_roles=parsed.preferred_roles,
        raw_json={
            "detected_headings": parsed.detected_headings,
            "sections": parsed.sections,
            "markdown": parsed.markdown,
            "markdown_hash": markdown_hash,
            "enriched_by_llm": enriched_by_llm,
            "full_time_experience_years": parsed.full_time_experience_years,
            "internship_months": parsed.internship_months,
            "is_fresher": parsed.is_fresher,
        },
        embedding=embedding,
        content_hash=content_hash,
    )

    # 7. Match Lifecycle Contract:
    # Identical content AND a full set of explained matches already saved -> bypass worker (0 tokens).
    # Otherwise (new/changed resume, or an incomplete earlier run) -> enqueue; cached LLM evaluations
    # mean only jobs without an explanation are sent to Groq.
    matching_worker.cancel_retry(user.id)
    existing_matches = await asyncio.to_thread(get_persisted_matches, user.id, DISPLAY_LIMIT)
    if is_cache_hit and len(existing_matches) >= DISPLAY_LIMIT:
        task_tracker.mark_completed(user.id)
    else:
        if not is_cache_hit:
            # Content changed: old matches and cached evaluations belong to the previous resume.
            await asyncio.to_thread(clear_user_matches, user.id)
        task_tracker.set_progress(
            user.id,
            status="processing",
            progress=50,
            step_label="Synthesizing vector embedding & enqueueing matching funnel...",
        )
        await matching_worker.enqueue(user_id=user.id, region="india", limit=DISPLAY_LIMIT)

    # 2-4. The funnel above only needs the parsed profile, so it is already running while the file uploads.
    # Now wait for the storage upload (started at the top) and record the resume.
    try:
        storage_path = await upload_task
        new_record, old_storage_path = await asyncio.to_thread(
            save_active_resume_record,
            user_id=user.id,
            filename=original_name,
            storage_path=storage_path,
            file_size=len(doc.raw_bytes),
            mime_type=doc.content_type,
            raw_text=doc.extracted_text,
        )
    except Exception:
        task_tracker.mark_failed(user.id, "Could not store the resume file. Please try again.")
        raise

    # Purge the previous file from storage in the background (the response does not need to wait for it)
    if old_storage_path and old_storage_path != storage_path:
        _fire_and_forget(delete_resume_from_storage(old_storage_path))

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


@app.get("/matches/status")
async def get_matches_status(user: AuthenticatedUser = Depends(get_current_user)):
    """Returns the live progress and status of the matching funnel for the authenticated user."""
    return task_tracker.get_progress(user.id)


def filter_matches_by_region(matches: list, region: str) -> list:
    """Region view over the saved matches (read-only; a miss returns an empty list, never a rerun)."""
    if region == "all":
        return list(matches)
    if region == "india":
        return [m for m in matches if m.get("region") in ("india", "remote")]
    if region == "us":
        return [m for m in matches if m.get("region") in ("us", "remote")]
    return [m for m in matches if m.get("region") == region]


@app.get("/matches")
async def get_matches(
    region: Optional[str] = Query("india", description="Target region: india, us, remote, or all"),
    limit: Optional[int] = Query(DISPLAY_LIMIT, ge=1, le=DISPLAY_LIMIT, description="Max matches to return"),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Returns the user's explained top matches (max 10). READ-ONLY: never runs the funnel inside the request.

    If nothing is saved and no run is active, a background run is enqueued through the worker
    (deduplicated, with a cooldown) and a `processing` state is returned for the client to poll.
    """
    limit = limit or DISPLAY_LIMIT
    persisted = await asyncio.to_thread(get_persisted_matches, user.id, DISPLAY_LIMIT)
    filtered = filter_matches_by_region(persisted, region or "india")[:limit]
    progress = task_tracker.get_progress(user.id)

    busy = bool(
        progress["status"] == "processing"
        or progress.get("analysis_pending")
        or matching_worker.has_scheduled_retry(user.id)
        or user.id in matching_worker.pending_users
    )

    if not busy and not persisted:
        age = time.time() - progress["updated_at"]
        may_start = progress["status"] == "idle" or age > ENQUEUE_COOLDOWN_SECONDS
        if may_start and await asyncio.to_thread(candidate_ready, user.id):
            task_tracker.set_progress(
                user.id,
                status="processing",
                progress=50,
                step_label="Starting match analysis...",
            )
            await matching_worker.enqueue(user_id=user.id, region="india", limit=DISPLAY_LIMIT)
            busy = True

    if busy:
        state = "processing"
    elif not persisted and progress["status"] == "failed":
        state = "failed"
    else:
        state = "ready"

    return {
        "matches": filtered,
        "total_evaluated": len(persisted),
        "live_fallback_triggered": False,
        "strong_matches_count": sum(1 for m in filtered if m["match_score"] >= 60),
        "status": state,
        "analysis_pending": busy,
        "error": progress.get("error") if state == "failed" else None,
    }
