import os, psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor(cursor_factory=RealDictCursor)

cur.execute("SELECT id, email FROM auth.users WHERE email = 'medhansh541@gmail.com';")
user = cur.fetchone()
print("USER:", user)

if user:
    uid = user["id"]
    cur.execute("SELECT id, filename, file_size, storage_path, created_at FROM public.resumes WHERE user_id = %s;", (uid,))
    resumes = cur.fetchall()
    print("RESUMES:", resumes)

    cur.execute("SELECT user_id, headline, skills, experience_years, (embedding IS NOT NULL) as has_emb, updated_at FROM public.profiles WHERE user_id = %s;", (uid,))
    profile = cur.fetchone()
    print("PROFILE:", profile)

    cur.execute("SELECT COUNT(*) as match_count FROM public.matches WHERE user_id = %s;", (uid,))
    matches = cur.fetchone()
    print("MATCHES COUNT:", matches)

    cur.execute("SELECT m.match_score, j.title, j.company FROM public.matches m JOIN public.jobs j ON m.job_id = j.id WHERE m.user_id = %s ORDER BY m.match_score DESC LIMIT 5;", (uid,))
    top = cur.fetchall()
    print("TOP MATCHES IN DB:", top)

conn.close()
