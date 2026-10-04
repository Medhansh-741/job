import os
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Tuple, Dict, Any
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

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

            # 3. Clear old matches and profiles
            cur.execute("DELETE FROM public.matches WHERE user_id = %s;", (user_id,))
            cur.execute("DELETE FROM public.profiles WHERE user_id = %s;", (user_id,))

            conn.commit()

    return new_record, old_storage_path


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

    return old_storage_path
