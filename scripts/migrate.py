import os
from pathlib import Path
import psycopg2
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in .env")

SCHEMA_SQL = """
-- 1. Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Resumes Table
CREATE TABLE IF NOT EXISTS public.resumes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Unique index to guarantee at most one active resume per user
CREATE UNIQUE INDEX IF NOT EXISTS unique_user_active_resume ON public.resumes (user_id) WHERE is_active = true;

-- 3. Jobs Catalog Table
CREATE TABLE IF NOT EXISTS public.jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    normalized_company TEXT,
    normalized_title TEXT,
    location TEXT NOT NULL,
    region TEXT DEFAULT 'All',
    category TEXT,
    description TEXT NOT NULL,
    source_url TEXT,
    date_posted TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active BOOLEAN NOT NULL DEFAULT true,
    required_years INTEGER,
    skills TEXT[] DEFAULT '{}',
    embedding vector(384),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Alter table in case it was created in earlier migration
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS normalized_company TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS normalized_title TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS required_years INTEGER;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS skills TEXT[] DEFAULT '{}';

-- 4. Candidate Profiles
CREATE TABLE IF NOT EXISTS public.profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    headline TEXT,
    skills TEXT[] DEFAULT '{}',
    experience_years NUMERIC,
    preferred_roles TEXT[] DEFAULT '{}',
    embedding vector(384),
    content_hash TEXT DEFAULT NULL,
    raw_json JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS content_hash TEXT DEFAULT NULL;

-- 5. Matches Table
CREATE TABLE IF NOT EXISTS public.matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
    match_score INTEGER NOT NULL,
    matched_skills TEXT[] DEFAULT '{}',
    missing_skills TEXT[] DEFAULT '{}',
    explanation TEXT,
    score_breakdown JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT unique_user_job_match UNIQUE (user_id, job_id)
);

ALTER TABLE public.matches ADD COLUMN IF NOT EXISTS score_breakdown JSONB DEFAULT '{}'::jsonb;

-- 6. Indexes
CREATE INDEX IF NOT EXISTS idx_resumes_user_id ON public.resumes(user_id);
CREATE INDEX IF NOT EXISTS idx_matches_user_score ON public.matches(user_id, match_score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_region ON public.jobs(region);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON public.jobs(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_is_active ON public.jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_jobs_norm_comp_title ON public.jobs(normalized_company, normalized_title, region);
CREATE INDEX IF NOT EXISTS idx_jobs_embedding_hnsw ON public.jobs USING hnsw (embedding vector_cosine_ops);

-- 7. Stored Procedure for Cosine Vector Matching
CREATE OR REPLACE FUNCTION match_jobs (
    query_embedding vector(384),
    match_threshold float DEFAULT 0.0,
    match_count int DEFAULT 100,
    filter_region text DEFAULT NULL,
    filter_max_years int DEFAULT NULL,
    is_fresher_candidate boolean DEFAULT false
)
RETURNS TABLE (
    id text,
    title text,
    company text,
    normalized_company text,
    normalized_title text,
    location text,
    region text,
    description text,
    source_url text,
    date_posted timestamptz,
    last_seen_at timestamptz,
    required_years int,
    skills text[],
    similarity float
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    -- Explores 150 graph nodes to guarantee complete Top-100 exploration
    PERFORM set_config('hnsw.ef_search', '150', true);

    RETURN QUERY
    SELECT
        j.id,
        j.title,
        j.company,
        j.normalized_company,
        j.normalized_title,
        j.location,
        j.region,
        j.description,
        j.source_url,
        j.date_posted,
        j.last_seen_at,
        j.required_years,
        j.skills,
        (1 - (j.embedding <=> query_embedding))::float AS similarity
    FROM public.jobs j
    WHERE j.is_active = true
      AND j.embedding IS NOT NULL
      AND (1 - (j.embedding <=> query_embedding)) >= match_threshold
      -- Hard Seniority Boundary Exclusion
      -- 1. All candidates: exclude executive/director titles
      AND NOT (
          j.normalized_title ~* '\y(director|vp|vice president|head of)\y'
          OR j.title ~* '\y(director|vp|vice president|head of)\y'
      )
      -- 2. Freshers strictly: hard knockout of Senior, Lead, Architect, Manager, Staff, Principal
      AND (
          NOT is_fresher_candidate OR
          NOT (
              j.normalized_title ~* '\y(senior|sr\.?|lead|architect|manager|mgr|staff|principal)\y'
              OR j.title ~* '\y(senior|sr\.?|lead|architect|manager|mgr|staff|principal)\y'
          )
      )
      -- Region Invariant: 'india' includes 'remote'; 'us' includes 'remote'
      AND (
          filter_region IS NULL OR filter_region = 'all' OR
          (filter_region = 'india' AND j.region IN ('india', 'remote')) OR
          (filter_region = 'us' AND j.region IN ('us', 'remote')) OR
          (filter_region = 'remote' AND j.region = 'remote') OR
          (filter_region NOT IN ('india', 'us', 'remote', 'all') AND j.region = filter_region)
      )
      -- Experience Invariant: Freshers see <= 1 OR NULL; Experienced see <= (Y+1) OR NULL
      AND (
          j.required_years IS NULL OR
          (is_fresher_candidate AND j.required_years <= 1) OR
          (NOT is_fresher_candidate AND (filter_max_years IS NULL OR j.required_years <= (filter_max_years + 1)))
      )
    ORDER BY j.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- 7. RLS
ALTER TABLE public.resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.matches ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can view own resumes' AND tablename = 'resumes') THEN
        CREATE POLICY "Users can view own resumes" ON public.resumes FOR SELECT USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can modify own resumes' AND tablename = 'resumes') THEN
        CREATE POLICY "Users can modify own resumes" ON public.resumes FOR ALL USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Authenticated users can read jobs' AND tablename = 'jobs') THEN
        CREATE POLICY "Authenticated users can read jobs" ON public.jobs FOR SELECT TO authenticated USING (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users view own profile' AND tablename = 'profiles') THEN
        CREATE POLICY "Users view own profile" ON public.profiles FOR ALL USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users view own matches' AND tablename = 'matches') THEN
        CREATE POLICY "Users view own matches" ON public.matches FOR ALL USING (auth.uid() = user_id);
    END IF;
END $$;
"""

def main():
    print(f"Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        print("Executing schema migration...")
        cur.execute(SCHEMA_SQL)
        print("Schema successfully applied!")
        
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]
        print(f"Verified Public Tables: {tables}")
    conn.close()

if __name__ == "__main__":
    main()
