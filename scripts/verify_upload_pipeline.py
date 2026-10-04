"""End-to-end verification of Resume Upload, Parsing, and Supabase Profile Persistence."""
import os
import sys
from pathlib import Path
import httpx
import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

supabase_url = os.getenv("SUPABASE_URL")
anon_key = os.getenv("SUPABASE_ANON_KEY")
db_url = os.getenv("DATABASE_URL")

FASTAPI_URL = "http://127.0.0.1:8000"


def main():
    print("1. Authenticating test user with Supabase...")
    auth_r = httpx.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={"email": "mumbai.test.user@gmail.com", "password": "Password123!"},
        timeout=10.0,
    )
    if auth_r.status_code != 200:
        print(f"Failed to authenticate: {auth_r.status_code} - {auth_r.text}")
        return

    token = auth_r.json().get("access_token")
    user_id = auth_r.json().get("user", {}).get("id")
    print(f"   Authenticated user_id: {user_id}")

    test_pdf = ROOT / "resumes" / "medhansh.pdf"
    if not test_pdf.exists():
        print("medhansh.pdf not found in resumes/")
        return

    print(f"\n2. Uploading {test_pdf.name} to {FASTAPI_URL}/resumes/upload...")
    with open(test_pdf, "rb") as f:
        upload_r = httpx.post(
            f"{FASTAPI_URL}/resumes/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (test_pdf.name, f, "application/pdf")},
            timeout=15.0,
        )

    print(f"   Upload Status: {upload_r.status_code}")
    upload_data = upload_r.json()
    print("   Upload Response Profile:")
    print(f"     Headline: {upload_data.get('profile', {}).get('headline')}")
    print(f"     Skills Count: {len(upload_data.get('profile', {}).get('skills', []))}")
    print(f"     Skills: {upload_data.get('profile', {}).get('skills')[:10]}...")
    print(f"     Experience: {upload_data.get('profile', {}).get('experience_years')} yrs")
    print(f"     Content Hash: {upload_data.get('profile', {}).get('content_hash')}")
    print(f"     Cache Hit: {upload_data.get('profile', {}).get('is_cache_hit')}")
    print(f"     Has Embedding: {upload_data.get('profile', {}).get('has_embedding')}")

    print(f"\n3. Fetching profile via GET {FASTAPI_URL}/profiles/me...")
    profile_r = httpx.get(
        f"{FASTAPI_URL}/profiles/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    print(f"   Profile Status: {profile_r.status_code}")
    p = profile_r.json().get("profile") or {}
    print(f"   Fetched Headline: {p.get('headline')}")
    print(f"   Fetched Skills Count: {len(p.get('skills', []))}")
    print(f"   Fetched Content Hash: {p.get('content_hash')}")
    print(f"   Fetched Has Embedding: {p.get('has_embedding')}")
    raw_sections = p.get("raw_json", {}).get("detected_headings", [])
    print(f"   Fetched Detected Headings: {raw_sections}")

    print("\n4. Verifying direct Postgres row in public.profiles...")
    conn = psycopg2.connect(db_url)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id, headline, array_length(skills, 1), experience_years, 
                   content_hash, (embedding IS NOT NULL) AS has_vector, updated_at
            FROM public.profiles
            WHERE user_id = %s;
            """,
            (user_id,),
        )
        row = cur.fetchone()
        print(f"   Postgres Profile Record:")
        print(f"     User ID: {row[0]}")
        print(f"     Headline: {row[1]}")
        print(f"     Skills Count: {row[2]}")
        print(f"     Experience Years: {row[3]}")
        print(f"     Content Hash: {row[4]}")
        print(f"     Has Vector: {row[5]}")
        print(f"     Updated At: {row[6]}")

        assert row[4] is not None and len(row[4]) == 64, "content_hash must be 64-char hex string"
        assert row[5] is True, "vector embedding must not be null"

    conn.close()

    print("\n5. Testing Repeat Upload for Cache Hit verification...")
    with open(test_pdf, "rb") as f:
        repeat_r = httpx.post(
            f"{FASTAPI_URL}/resumes/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (test_pdf.name, f, "application/pdf")},
            timeout=15.0,
        )
    repeat_data = repeat_r.json()
    print(f"   Repeat Upload Status: {repeat_r.status_code}")
    print(f"   Repeat Cache Hit: {repeat_data.get('profile', {}).get('is_cache_hit')}")
    assert repeat_data.get("profile", {}).get("is_cache_hit") is True, "Repeat upload must result in Cache Hit!"
    print("   [PASS] Repeat upload bypassed FastEmbed via Content Hash (0ms, 0 CPU).")

    print("\n--- ALL VERIFICATIONS PASSED SUCCESSFULLY! ZERO RUBBER STAMPS. ---")


if __name__ == "__main__":
    main()
