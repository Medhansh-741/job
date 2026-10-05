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
  const [searchQuery, setSearchQuery] = React.useState("");
  const [regionFilter, setRegionFilter] = React.useState<"all" | "india" | "us" | "remote">("all");
  const [sortBy, setSortBy] = React.useState<"match" | "newest">("match");

  // Active resume state fetched from backend
  const isExplicitEmpty = searchParams.get("empty") === "true";
  const [hasResume, setHasResume] = React.useState<boolean>(!isExplicitEmpty);
  const [loadingResume, setLoadingResume] = React.useState<boolean>(true);

  // Live jobs state from backend matching engine
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [loadingJobs, setLoadingJobs] = React.useState<boolean>(false);

  const fetchMatches = React.useCallback(async (targetRegion: string) => {
    setLoadingJobs(true);
    try {
      const regionParam = targetRegion === "all" ? "all" : targetRegion;
      const res = await fetch(`/api/backend/matches?region=${encodeURIComponent(regionParam)}&limit=15`);
      if (res.ok) {
        const data = await res.json();
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

  // Fetch live matches when resume is active or region filter changes
  React.useEffect(() => {
    if (hasResume) {
      fetchMatches(regionFilter);
    } else {
      setJobs([]);
    }
  }, [hasResume, regionFilter, fetchMatches]);

  // Read selected job ID from URL query parameters (?jobId=...)
  const selectedJobId = searchParams.get("jobId");
  const selectedJob = React.useMemo(() => {
    return jobs.find((j) => j.id === selectedJobId) || null;
  }, [jobs, selectedJobId]);

  const handleSelectJob = (id: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("jobId", id);
    router.push(`/dashboard?${params.toString()}`);
  };

  const handleCloseModal = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("jobId");
    const query = params.toString();
    router.push(query ? `/dashboard?${query}` : "/dashboard");
  };

  // Filter and sort jobs
  const filteredJobs = React.useMemo(() => {
    return jobs.filter((job) => {
      // Region filter: if not 'all', check match (India and US queries already expand to include remote)
      if (regionFilter !== "all" && job.region !== regionFilter && job.region !== "remote") {
        return false;
      }
      // Search query filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesTitle = job.title.toLowerCase().includes(q);
        const matchesCompany = job.company.toLowerCase().includes(q);
        const matchesSkill = job.matchedSkills.some((s) => s.toLowerCase().includes(q));
        if (!matchesTitle && !matchesCompany && !matchesSkill) {
          return false;
        }
      }
      return true;
    }).sort((a, b) => {
      if (sortBy === "match") {
        return b.matchScore - a.matchScore;
      }
      return 0;
    });
  }, [jobs, searchQuery, regionFilter, sortBy]);

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
        <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/95 backdrop-blur-xs px-3.5 sm:px-6 py-3 space-y-2.5">
          {/* Row 1: Hamburger Menu (Mobile), Search Input */}
          <div className="flex items-center gap-2.5 w-full">
            {/* Mobile Hamburger Toggle */}
            <button
              type="button"
              onClick={() => setMobileSidebarOpen(true)}
              aria-label="Open menu"
              className="md:hidden flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50"
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

            {/* Search Input (Takes all remaining width) */}
            <div className="relative flex-1 min-w-0">
              <svg
                className="absolute left-3 top-2.5 h-4 w-4 text-zinc-400"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by role, company, or skill..."
                disabled={!hasResume}
                className="w-full rounded-md border border-zinc-200 bg-zinc-50 pl-9 pr-3 py-1.5 text-xs text-zinc-900 placeholder:text-zinc-400 focus:border-zinc-900 focus:bg-white focus:outline-none focus:ring-1 focus:ring-zinc-900 transition-colors disabled:opacity-50"
              />
            </div>
          </div>

          {/* Row 2: Region Filters (Horizontal scroll on mobile) & Sort */}
          <div className="flex items-center justify-between gap-2 w-full">
            {/* Scrollable Region Filter Chips */}
            <div className="flex items-center overflow-x-auto rounded-lg border border-zinc-200 bg-zinc-50 p-0.5 text-xs shrink-0 max-w-[calc(100%-110px)] sm:max-w-none">
              {(["all", "india", "us", "remote"] as const).map((r) => (
                <button
                  key={r}
                  type="button"
                  disabled={!hasResume}
                  onClick={() => setRegionFilter(r)}
                  className={`rounded-md px-2 sm:px-2.5 py-1 text-[11px] sm:text-xs capitalize transition-colors shrink-0 disabled:opacity-40 ${
                    regionFilter === r
                      ? "bg-white font-medium text-zinc-900 shadow-2xs"
                      : "text-zinc-500 hover:text-zinc-900"
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>

            {/* Sort Dropdown */}
            <select
              value={sortBy}
              disabled={!hasResume}
              onChange={(e) => setSortBy(e.target.value as "match" | "newest")}
              className="rounded-lg border border-zinc-200 bg-white px-2 py-1 text-[11px] sm:text-xs text-zinc-800 focus:border-zinc-900 focus:outline-none focus:ring-1 focus:ring-zinc-900 cursor-pointer shrink-0 disabled:opacity-40"
            >
              <option value="match">Highest %</option>
              <option value="newest">Newest</option>
            </select>
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
            </div>

            {filteredJobs.length === 0 ? (
              <div className="rounded-xl border border-zinc-200 bg-white p-8 sm:p-12 text-center">
                <p className="text-sm font-medium text-zinc-900">No matching roles found</p>
                <p className="mt-1 text-xs text-zinc-500">
                  Try adjusting your search query or region filter.
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
          fetchMatches(regionFilter);
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
