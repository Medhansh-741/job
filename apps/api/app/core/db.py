import os
import json
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Tuple, Dict, Any, List
from dotenv import load_dotenv
import psycopg2
import psycopg2.errors
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, execute_values

ROOT_ENV = Path(__file__).resolve().parent.parent.parent.parent.parent / ".env"
if ROOT_ENV.exists():
    load_dotenv(ROOT_ENV)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Initialize connection pool (min 1, max 10)
_pool: Optional[pool.SimpleConnectionPool] = None

def get_pool() -> pool.SimpleConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set in environment")
        _pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
    return _pool


@contextmanager
def get_db():
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
    finally:
        p.putconn(conn)


def get_active_resume_record(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve the single active resume for a user, or None."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, user_id, filename, storage_path, file_size, mime_type, 
                       raw_text, is_active, created_at, updated_at
                FROM public.resumes
                WHERE user_id = %s AND is_active = true
                LIMIT 1;
                """,
                (user_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


def save_active_resume_record(
    user_id: str,
    filename: str,
    storage_path: str,
    file_size: int,
    mime_type: str,
    raw_text: str,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Saves a new active resume for the user.
    If an active resume already exists, it marks it inactive and returns the old storage_path
    so the physical file can be purged from storage.
    Also wipes stale match/profile data so fresh ones can be computed.
    """
    old_storage_path: Optional[str] = None

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Fetch current active resume if any
            cur.execute(
                """
                SELECT storage_path FROM public.resumes
                WHERE user_id = %s AND is_active = true;
                """,
                (user_id,)
            )
            old_row = cur.fetchone()
            if old_row:
                old_storage_path = old_row["storage_path"]
                # Delete previous resume records for clean 1-resume invariant
                cur.execute(
                    "DELETE FROM public.resumes WHERE user_id = %s;",
                    (user_id,)
                )

            # 2. Insert new active resume
            cur.execute(
                """
                INSERT INTO public.resumes (
                    user_id, filename, storage_path, file_size, mime_type, raw_text, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, true)
                RETURNING id, user_id, filename, storage_path, file_size, mime_type, 
                          is_active, created_at, updated_at;
                """,
                (user_id, filename, storage_path, file_size, mime_type, raw_text)
            )
            new_record = dict(cur.fetchone())

            # Matches are NOT cleared here: the upload flow decides (by content hash) whether the
            # existing matches are still valid, so an identical re-upload costs 0 tokens.
            conn.commit()

    return new_record, old_storage_path


def clear_user_matches(user_id: str) -> None:
    """Drops a user's saved matches and cached LLM evaluations (resume content changed)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.matches WHERE user_id = %s;", (user_id,))
        conn.commit()
    purge_evaluations(user_id)


def delete_active_resume_record(user_id: str) -> Optional[str]:
    """
    Deletes the user's active resume record and cascades to matches and profile.
    Returns the storage_path of the removed resume so storage can be cleaned up.
    """
    old_storage_path: Optional[str] = None

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Find existing active resume
            cur.execute(
                """
                SELECT storage_path FROM public.resumes
                WHERE user_id = %s AND is_active = true;
                """,
                (user_id,)
            )
            row = cur.fetchone()
            if row:
                old_storage_path = row["storage_path"]

            # 2. Delete all records for this user (cascading cleanup)
            cur.execute("DELETE FROM public.resumes WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM public.matches WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM public.profiles WHERE user_id = %s;", (user_id,))

            conn.commit()

    purge_evaluations(user_id)
    return old_storage_path


# ---------------------------------------------------------------------------
# LLM evaluation cache (public.llm_evaluations). Best-effort: if the table does not
# exist yet or a query fails, callers simply behave as a cache miss.
# ---------------------------------------------------------------------------
_logger = logging.getLogger("db")
_EVAL_TABLE_WARNED = False


def _warn_eval_table(exc: Exception) -> None:
    global _EVAL_TABLE_WARNED
    if isinstance(exc, psycopg2.errors.UndefinedTable):
        if not _EVAL_TABLE_WARNED:
            _EVAL_TABLE_WARNED = True
            _logger.warning("public.llm_evaluations does not exist yet; LLM result caching is disabled.")
    else:
        _logger.warning("llm_evaluations cache error: %s", exc)


def get_cached_evaluations(user_id: str, content_hash: str, job_ids: List[str]) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """Returns {job_id: (job_sig, evaluation)} for cached LLM evaluations of this resume version."""
    if not user_id or not content_hash or not job_ids:
        return {}
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT job_id, job_sig, evaluation
                    FROM public.llm_evaluations
                    WHERE user_id = %s AND content_hash = %s AND job_id = ANY(%s);
                    """,
                    (user_id, content_hash, list(job_ids)),
                )
                return {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    except Exception as exc:
        _warn_eval_table(exc)
        return {}


def put_cached_evaluations(user_id: str, content_hash: str, items: Dict[str, Tuple[str, Dict[str, Any]]]) -> None:
    """Upserts {job_id: (job_sig, evaluation)} for this resume version."""
    if not user_id or not content_hash or not items:
        return
    rows = [(user_id, content_hash, job_id, sig, json.dumps(ev)) for job_id, (sig, ev) in items.items()]
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO public.llm_evaluations (user_id, content_hash, job_id, job_sig, evaluation)
                    VALUES %s
                    ON CONFLICT (user_id, content_hash, job_id) DO UPDATE SET
                        job_sig = EXCLUDED.job_sig,
                        evaluation = EXCLUDED.evaluation,
                        created_at = now();
                    """,
                    rows,
                    template="(%s, %s, %s, %s, %s::jsonb)",
                )
            conn.commit()
    except Exception as exc:
        _warn_eval_table(exc)


def purge_evaluations(user_id: str) -> None:
    """Deletes every cached LLM evaluation for a user (resume deleted or replaced)."""
    if not user_id:
        return
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM public.llm_evaluations WHERE user_id = %s;", (user_id,))
            conn.commit()
    except Exception as exc:
        _warn_eval_table(exc)


def save_candidate_profile(
    user_id: str,
    headline: Optional[str],
    skills: List[str],
    experience_years: float,
    preferred_roles: List[str],
    raw_json: Dict[str, Any],
    embedding: Optional[List[float]] = None,
    content_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomic upsert of candidate profile attributes, vector embedding, content hash, and dynamic raw_json."""
    emb_val = str(embedding) if embedding else None

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO public.profiles (
                    user_id, headline, skills, experience_years, preferred_roles,
                    embedding, content_hash, raw_json, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    headline = EXCLUDED.headline,
                    skills = EXCLUDED.skills,
                    experience_years = EXCLUDED.experience_years,
                    preferred_roles = EXCLUDED.preferred_roles,
                    embedding = EXCLUDED.embedding,
                    content_hash = EXCLUDED.content_hash,
                    raw_json = EXCLUDED.raw_json,
                    updated_at = now()
                RETURNING user_id, headline, skills, experience_years, preferred_roles,
                          content_hash, (embedding IS NOT NULL) AS has_embedding, raw_json, updated_at;
                """,
                (
                    user_id,
                    headline,
                    skills,
                    experience_years,
                    preferred_roles,
                    emb_val,
                    content_hash,
                    json.dumps(raw_json),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row)


def candidate_ready(user_id: str) -> bool:
    """Cheap check: does the user have a profile with skills and an embedding (without loading the vector)?"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT (embedding IS NOT NULL AND COALESCE(cardinality(skills), 0) > 0)
                FROM public.profiles WHERE user_id = %s;
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return bool(row and row[0])


def get_candidate_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve structured candidate profile from Supabase."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT user_id, headline, skills, experience_years, preferred_roles,
                       content_hash, embedding, (embedding IS NOT NULL) AS has_embedding,
                       raw_json, updated_at
                FROM public.profiles
                WHERE user_id = %s;
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
