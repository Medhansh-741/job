"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/dashboard/sidebar";
import { JobCard } from "@/components/dashboard/job-card";
import { JobModal } from "@/components/dashboard/job-modal";
import { UploadModal } from "@/components/dashboard/upload-modal";
import { Button } from "@/components/ui/button";
import { Job } from "@/types/job";

function DashboardContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = React.useState(false);
  const [uploadModalOpen, setUploadModalOpen] = React.useState(false);

  // Active resume state fetched from backend
  const isExplicitEmpty = searchParams.get("empty") === "true";
  const [hasResume, setHasResume] = React.useState<boolean>(!isExplicitEmpty);
  const [loadingResume, setLoadingResume] = React.useState<boolean>(true);

  // Live jobs state from backend matching engine
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [loadingJobs, setLoadingJobs] = React.useState<boolean>(false);
  // True while the backend is still producing (or retrying) AI explanations for matches
  const [analysisPending, setAnalysisPending] = React.useState<boolean>(false);
  const [analysisLabel, setAnalysisLabel] = React.useState<string>("");
  const [matchesError, setMatchesError] = React.useState<string | null>(null);

  const fetchMatches = React.useCallback(async (targetRegion: string = "india") => {
    setLoadingJobs(true);
    try {
      const res = await fetch(`/api/backend/matches?region=${encodeURIComponent(targetRegion)}&limit=10`, {
        cache: "no-store",
      });
      if (res.ok) {
        const data = await res.json();
        setAnalysisPending(data.status === "processing" || Boolean(data.analysis_pending));
        setMatchesError(data.status === "failed" ? data.error || "Match analysis failed." : null);
        const rawMatches = data.matches || [];
        const formatted: Job[] = rawMatches.map((m: any) => ({
          id: m.id,
          title: m.title,
          company: m.company,
          location: m.location || "Remote",
          region: (m.region as "india" | "us" | "remote") || "india",
          matchScore: m.match_score,
          matchedSkills: m.matched_skills || [],
          inferredSkills: m.inferred_skills || m.score_breakdown?.inferred_skills || [],
          missingSkills: m.missing_skills || [],
          explanation: m.explanation || "",
          scoreBreakdown: m.score_breakdown || {},
          description: m.description || "",
          url: m.source_url || "#",
          postedAt: m.date_posted ? new Date(m.date_posted).toLocaleDateString() : undefined,
          ats: m.id.includes(":") ? m.id.split(":")[0] : undefined,
        }));
        setJobs(formatted);
      }
    } catch (err) {
      console.error("Failed to load matches:", err);
    } finally {
      setLoadingJobs(false);
    }
  }, []);

  React.useEffect(() => {
    if (isExplicitEmpty) {
      setHasResume(false);
      setLoadingResume(false);
      return;
    }
    fetch("/api/backend/resumes/active")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && data.active) {
          setHasResume(true);
        } else {
          setHasResume(false);
        }
      })
      .catch(() => {
        setHasResume(false);
      })
      .finally(() => {
        setLoadingResume(false);
      });
  }, [isExplicitEmpty]);

  // Fetch live matches when resume is active
  React.useEffect(() => {
    if (hasResume) {
      fetchMatches("india");
    } else {
      setJobs([]);
      setAnalysisPending(false);
      setMatchesError(null);
    }
  }, [hasResume, fetchMatches]);

  // While AI analysis is pending, poll the tiny /matches/status endpoint with backoff.
  // Skips requests while the tab is hidden, stops when done (then refetches matches once) or after 10 min.
  React.useEffect(() => {
    if (!hasResume || !analysisPending) return;
    let cancelled = false;
    let delay = 3000;
    const startedAt = Date.now();
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      if (cancelled || Date.now() - startedAt > 10 * 60 * 1000) return;
      if (document.visibilityState !== "hidden") {
        try {
          const res = await fetch("/api/backend/matches/status", { cache: "no-store" });
          if (res.ok) {
            const status = await res.json();
            if (cancelled) return;
            setAnalysisLabel(status.step_label || "");
            const stillWorking = status.status === "processing" || Boolean(status.analysis_pending);
            if (!stillWorking) {
              await fetchMatches("india");
              return;
            }
            // A scheduled retry is minutes away: poll slowly. Otherwise back off up to 10s.
            delay =
              status.status !== "processing" && status.retry_in
                ? Math.min(Math.max((status.retry_in * 1000) / 2, 5000), 30000)
                : Math.min(delay * 1.5, 10000);
          }
        } catch {
          // temporary network blip: keep polling
        }
      }
      if (!cancelled) timer = setTimeout(tick, delay);
    };

    timer = setTimeout(tick, delay);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [hasResume, analysisPending, fetchMatches]);

  // Read selected job ID from URL query parameters (?jobId=...)
  const selectedJobId = searchParams.get("jobId");
  const selectedJob = React.useMemo(() => {
    return jobs.find((j) => j.id === selectedJobId) || null;
  }, [jobs, selectedJobId]);

  const handleSelectJob = React.useCallback(
    (id: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("jobId", id);
      router.push(`/dashboard?${params.toString()}`);
    },
    [router, searchParams]
  );

  const handleCloseModal = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("jobId");
    const query = params.toString();
    router.push(query ? `/dashboard?${query}` : "/dashboard");
  };

  // Curated matches are already ranked in strict descending order of fit
  const filteredJobs = jobs;

  return (
    <div className="flex min-h-dvh bg-zinc-50">
      {/* Responsive Sidebar (Mobile Drawer + Desktop In-flow) */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        mobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
        onOpenUpload={() => setUploadModalOpen(true)}
      />

      {/* Main Content Area: 100% width on mobile */}
      <main className="flex-1 flex flex-col min-w-0 w-full">
        {/* Top Control Bar */}
        {/* Mobile Header Toggle */}
        <header className="md:hidden sticky top-0 z-10 border-b border-zinc-200 bg-white/95 backdrop-blur-xs px-3.5 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setMobileSidebarOpen(true)}
              aria-label="Open menu"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50"
            >
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <span className="text-sm font-semibold text-zinc-900">Job Matcher</span>
          </div>
        </header>

        {/* Content Body: Skeletons vs Clean Empty State vs Active Feed */}
        {loadingResume || (hasResume && loadingJobs && jobs.length === 0) ? (
          <div className="flex-1 p-3.5 sm:p-5 md:p-6 max-w-5xl w-full mx-auto space-y-3">
            <div className="h-3 w-36 rounded bg-zinc-200/70 animate-pulse" />
            <div className="space-y-2.5">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="rounded-xl border border-zinc-200 bg-white p-4 sm:p-5 shadow-xs animate-pulse space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <div className="h-4 w-1/3 rounded bg-zinc-200/70" />
                    <div className="h-5 w-16 rounded bg-zinc-100" />
                  </div>
                  <div className="h-3 w-1/4 rounded bg-zinc-100" />
                  <div className="flex gap-2">
                    <div className="h-5 w-14 rounded bg-zinc-100" />
                    <div className="h-5 w-14 rounded bg-zinc-100" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : !hasResume ? (
          <div className="flex-1 p-3.5 sm:p-5 md:p-6 max-w-xl w-full mx-auto flex items-center justify-center">
            <div className="w-full rounded-xl border border-zinc-200 bg-white p-8 sm:p-12 text-center space-y-4 shadow-xs">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-zinc-100 text-zinc-500">
                <svg
                  className="h-6 w-6"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
              </div>
              <div className="space-y-1">
                <h2 className="text-base font-semibold text-zinc-900">
                  No active resume found
                </h2>
                <p className="text-xs text-zinc-500 max-w-sm mx-auto">
                  Upload your resume in PDF or DOCX format to calculate match scores and discover recommended positions.
                </p>
              </div>
              <div>
                <Button
                  className="w-auto h-9 px-4 text-xs"
                  onClick={() => setUploadModalOpen(true)}
                >
                  Upload Resume
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex-1 p-3.5 sm:p-5 md:p-6 max-w-5xl w-full mx-auto space-y-3 sm:space-y-4">
            <div className="flex items-center justify-between text-xs text-zinc-500 pb-0.5">
              <span>
                Showing <strong className="text-zinc-900">{filteredJobs.length}</strong> matched roles
              </span>
              {analysisPending && filteredJobs.length > 0 && (
                <span className="inline-flex items-center gap-1.5 text-zinc-500">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                  Finishing AI analysis for more roles...
                </span>
              )}
            </div>

            {filteredJobs.length === 0 && analysisPending ? (
              <div className="rounded-xl border border-zinc-200 bg-white p-8 sm:p-12 text-center space-y-2">
                <div className="mx-auto h-1.5 w-40 overflow-hidden rounded-full bg-zinc-100">
                  <div className="h-full w-1/2 rounded-full bg-zinc-400 animate-pulse" />
                </div>
                <p className="text-sm font-medium text-zinc-900">AI analysis in progress</p>
                <p className="text-xs text-zinc-500">
                  {analysisLabel || "Evaluating your best matches. This page updates automatically."}
                </p>
              </div>
            ) : filteredJobs.length === 0 && matchesError ? (
              <div className="rounded-xl border border-zinc-200 bg-white p-8 sm:p-12 text-center space-y-3">
                <p className="text-sm font-medium text-zinc-900">Couldn&apos;t finish the AI analysis</p>
                <p className="text-xs text-zinc-500">{matchesError}</p>
                <Button className="w-auto h-8 px-3 text-xs" onClick={() => fetchMatches("india")}>
                  Try again
                </Button>
              </div>
            ) : filteredJobs.length === 0 ? (
              <div className="rounded-xl border border-zinc-200 bg-white p-8 sm:p-12 text-center">
                <p className="text-sm font-medium text-zinc-900">No matching roles found yet</p>
                <p className="mt-1 text-xs text-zinc-500">
                  Upload an updated resume to refresh your matches.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2.5 sm:gap-3.5">
                {filteredJobs.map((job) => (
                  <JobCard key={job.id} job={job} onSelect={handleSelectJob} />
                ))}
              </div>
            )}
          </div>
        )}
      </main>

      {/* Centered Modal with URL State & Blurred Backdrop */}
      <JobModal job={selectedJob} onClose={handleCloseModal} />

      {/* Upload Modal (Triggered by Sidebar or Empty State) */}
      <UploadModal
        open={uploadModalOpen}
        onClose={() => setUploadModalOpen(false)}
        onUploadSuccess={() => {
          setHasResume(true);
          setLoadingResume(false);
          fetchMatches("india");
        }}
      />
    </div>
  );
}

export default function DashboardPage() {
  return (
    <React.Suspense
      fallback={
        <div className="flex min-h-dvh items-center justify-center bg-zinc-50">
          <p className="text-xs text-zinc-400">Loading dashboard...</p>
        </div>
      }
    >
      <DashboardContent />
    </React.Suspense>
  );
}
