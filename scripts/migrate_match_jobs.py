import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

# Update the 6-parameter version of match_jobs
cur.execute("""
CREATE OR REPLACE FUNCTION public.match_jobs(
    query_embedding vector,
    match_threshold double precision DEFAULT 0.0,
    match_count integer DEFAULT 100,
    filter_region text DEFAULT NULL::text,
    filter_max_years integer DEFAULT NULL::integer,
    is_fresher_candidate boolean DEFAULT false
)
RETURNS TABLE(
    id text,
    title text,
    company text,
    normalized_company text,
    normalized_title text,
    location text,
    region text,
    description text,
    source_url text,
    date_posted timestamp with time zone,
    last_seen_at timestamp with time zone,
    required_years integer,
    skills text[],
    similarity double precision
)
LANGUAGE plpgsql
STABLE
AS $function$
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
          j.normalized_title ~* '\\y(director|vp|vice president|head of)\\y'
          OR j.title ~* '\\y(director|vp|vice president|head of)\\y'
      )
      -- 2. Freshers strictly: hard knockout of Senior, Lead, Architect, Manager, Staff, Principal
      AND (
          NOT is_fresher_candidate OR
          NOT (
              j.normalized_title ~* '\\y(senior|sr\\.?|lead|architect|manager|mgr|staff|principal)\\y'
              OR j.title ~* '\\y(senior|sr\\.?|lead|architect|manager|mgr|staff|principal)\\y'
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
      -- Negative Geographic Knockout for India Remote:
      -- When filter_region is 'india', exclude remote jobs that are restricted to non-India locations/timezones
      AND NOT (
          filter_region = 'india' AND j.region = 'remote' AND (
              j.location ~* '\\y(amer|us only|usa only|canada|uk|united kingdom|france|germany|emea|latam|europe only|apac only)\\y'
              OR j.title ~* '\\y(amer|emea|latam|apac)\\y'
          )
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
$function$;
""")

conn.commit()
print("Successfully migrated match_jobs stored procedure with negative geographic knockout!")
conn.close()
