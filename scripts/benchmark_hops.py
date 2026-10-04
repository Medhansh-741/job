import os
import socket
import time
from pathlib import Path
import httpx
import psycopg2
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

supabase_url = os.getenv("SUPABASE_URL")
anon_key = os.getenv("SUPABASE_ANON_KEY")
db_url = os.getenv("DATABASE_URL")

print("--- NEW MUMBAI (AP-SOUTH-1) BENCHMARK ---")

# Hop 1: Raw TCP connection to Mumbai DB Pooler
host = "aws-0-ap-south-1.pooler.supabase.com"
t0 = time.time()
s = socket.socket()
s.settimeout(5.0)
s.connect((host, 5432))
s.close()
tcp_ms = (time.time() - t0) * 1000
print(f"1. Raw TCP Latency to Mumbai Pooler ({host}): {tcp_ms:.1f}ms")

# Hop 2: Postgres SSL Handshake + Query execution
t0 = time.time()
conn = psycopg2.connect(db_url, connect_timeout=5)
handshake_ms = (time.time() - t0) * 1000
t1 = time.time()
cur = conn.cursor()
cur.execute("SELECT 1;")
cur.fetchone()
query_ms = (time.time() - t1) * 1000
conn.close()
print(f"2. Mumbai Supabase Handshake: {handshake_ms:.1f}ms | SQL Execute: {query_ms:.1f}ms")

# Hop 3: Local FastAPI Health Check
t0 = time.time()
r_fastapi = httpx.get("http://127.0.0.1:8000/health")
print(f"3. Local FastAPI /health: {(time.time() - t0)*1000:.1f}ms (Status {r_fastapi.status_code})")

# Hop 4: Next.js BFF Proxy -> FastAPI Health Check
t0 = time.time()
r_bff = httpx.get("http://127.0.0.1:3000/api/backend/health")
print(f"4. Next.js BFF -> FastAPI /health: {(time.time() - t0)*1000:.1f}ms (Status {r_bff.status_code})")

# Hop 5: Create or sign in user on Mumbai project
signup_r = httpx.post(
    f"{supabase_url}/auth/v1/signup",
    headers={"apikey": anon_key, "Content-Type": "application/json"},
    json={"email": "mumbai.test.user@gmail.com", "password": "Password123!"},
)
# Confirm user if newly created
user_data = signup_r.json()
user_id = user_data.get("id") or user_data.get("user", {}).get("id")
s_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if user_id:
    httpx.put(
        f"{supabase_url}/auth/v1/admin/users/{user_id}",
        headers={"apikey": s_key, "Authorization": f"Bearer {s_key}", "Content-Type": "application/json"},
        json={"email_confirm": True},
    )

auth_r = httpx.post(
    f"{supabase_url}/auth/v1/token?grant_type=password",
    headers={"apikey": anon_key, "Content-Type": "application/json"},
    json={"email": "mumbai.test.user@gmail.com", "password": "Password123!"},
)
token = auth_r.json().get("access_token")

# Hop 5: FastAPI /resumes/active
t0 = time.time()
r_active_api = httpx.get(
    "http://127.0.0.1:8000/resumes/active",
    headers={"Authorization": f"Bearer {token}"},
)
print(f"5. FastAPI /resumes/active (JWT + Mumbai DB query): {(time.time() - t0)*1000:.1f}ms (Status {r_active_api.status_code})")

# Hop 6: Next.js BFF /api/backend/resumes/active
t0 = time.time()
r_active_bff = httpx.get(
    "http://127.0.0.1:3000/api/backend/resumes/active",
    headers={"Authorization": f"Bearer {token}"},
)
print(f"6. Next.js BFF /api/backend/resumes/active (Full Stack): {(time.time() - t0)*1000:.1f}ms (Status {r_active_bff.status_code})")
print("---------------------------------------------")
