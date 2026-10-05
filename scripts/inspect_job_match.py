import os, psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor(cursor_factory=RealDictCursor)

cur.execute("""
    SELECT id, title, company, skills, description 
    FROM public.jobs 
    WHERE company ILIKE '%getwingapp%'
    LIMIT 1;
""")
job = cur.fetchone()
print("JOB ID:", job["id"])
print("JOB TITLE:", job["title"])
print("JOB SKILLS TAGGED:", job["skills"])
print("JOB DESC:", job["description"])

cur.execute("""
    SELECT m.user_id, m.match_score, m.matched_skills, m.missing_skills, p.skills as user_skills, p.headline, p.preferred_roles
    FROM public.matches m
    JOIN public.profiles p ON m.user_id = p.user_id
    WHERE m.job_id = %s;
""", (job["id"],))
matches = cur.fetchall()
for m in matches:
    print("USER ID:", m["user_id"])
    print("MATCH SCORE:", m["match_score"])
    print("MATCHED SKILLS:", m["matched_skills"])
    print("MISSING SKILLS:", m["missing_skills"])
    print("USER HEADLINE:", m["headline"])
    print("USER SKILLS:", m["user_skills"])
    print("USER ROLES:", m["preferred_roles"])

conn.close()
