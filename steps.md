Good catch. The GitHub Actions scheduled workflow (Loop 1) is the engine that keeps the catalog alive. 

Here is the revised flow with **GitHub Actions & Crawler Infrastructure** clearly mapped:

---

### **Step 1: Catalog Ingestion, Normalization & GitHub Actions Crawler**
*Defining the job catalog data and the automated crawling infrastructure.*
- **Data Contract & Normalization:** ATS adapters (Greenhouse, Lever, Ashby, SmartRecruiters), location/region classification, deduplication rules, and required-experience parsing.
- **GitHub Actions Workflow:** Cron schedule, runtime environment, secret injection (`DATABASE_URL`, API keys), rate limits, batch upserting, and failure handling.
- **Seeding vs. Cron:** Initial database seed vs. recurring GitHub Actions crawl.

---

### **Step 2: Resume Parsing & Candidate Profile Structuring**
*Defining what candidate data is extracted and how.*
- Candidate skill extraction: purely deterministic dictionary/regex matching vs. LLM-assisted normalization.
- Experience calculation and role preference inference.
- Schema definition for `profiles` table.

---

### **Step 3: Embedding Architecture & Railway Resource Guardrails**
*Ensuring zero OOM crashes on Railway with fast inference.*
- Embedding text payload (full text vs. skills vs. hybrid text chunk).
- FastEmbed ONNX configuration on Railway (`all-MiniLM-L6-v2`, `parallel=1`, memory < 150MB).
- pgvector index strategy (HNSW vs. Flat for this scale) and the SQL cosine similarity RPC function.

---

### **Step 4: Funnel & Deterministic Scoring Math**
*Locking down the mathematical formula so the LLM never decides rankings.*
- **Stage 1 (Hard Filters):** Seniority exclusion, region/location constraints, experience tolerance.
- **Stage 2 (Vector Retrieval):** Top-$K$ candidate pool selection from pgvector.
- **Stage 3 (Hybrid Formula):** Exact weights and definitions for Semantic Similarity vs. Skill Coverage (Jaccard vs. Recall) vs. Title Boosts.
- **Stage 4 (Live Fallback Trigger):** Exact mathematical cutoff score or count that triggers a live Adzuna/Jooble query.

---

### **Step 5: "Why It Matches" LLM Explanation Contract**
*Restricting the LLM strictly to translating mathematical signals into human bullets.*
- Grounding prompt design: feeding *only* computed match scores, matched skills, and missing skills to Groq.
- Format and token constraints (e.g., 2–3 crisp bullets, strict anti-hallucination guardrail).

---

### **Step 6: Trigger Mechanics, Async Pipeline & UI Notification**
*Tying the user-facing loop together.*
- Execution trigger (FastAPI `BackgroundTasks` upon upload).
- Pipeline state lifecycle (`uploading` → `parsing` → `embedding` → `scoring` → `ready`).
- How the frontend receives matches (polling vs. Supabase Realtime).

---

Does this updated 6-step flow look comprehensive, or would you like to tweak the order before we dive into Step 1?