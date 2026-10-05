"use client";

import * as React from "react";
import { Job } from "@/types/job";
import { Button } from "@/components/ui/button";

export interface JobModalProps {
  job: Job | null;
  onClose: () => void;
}

export function JobModal({ job, onClose }: JobModalProps) {
  // Handle ESC key to close
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!job) return null;

  const isExactMatch = job.matchScore >= 75 && job.matchedSkills.length >= 3;
  const breakdown = job.scoreBreakdown || {};
  const deductions = breakdown.deductions || [];

  // Every surfaced job has an AI verdict (the API hides unexplained jobs); never invent one.
  const explanation = breakdown.verdict || job.explanation || "";

  const strengths = job.matchedSkills.length > 0 ? job.matchedSkills : (breakdown.strengths || []);
  const gaps = (job.missingSkills && job.missingSkills.length > 0) ? job.missingSkills : (breakdown.gaps || []);

  // Clean description of awkward leading/trailing aggregator snippet artifacts
  const rawDescription = job.description || "";
  const cleanedDescription = rawDescription
    .replace(/^[\s\.\…\-–—]+/, "") // strip leading ... or hyphens
    .replace(/[\s\.\…]+$/, "")   // strip trailing ...
    .trim();

  const isAggregatorSnippet =
    rawDescription.includes("...") ||
    rawDescription.length < 350 ||
    job.id.startsWith("jooble:") ||
    job.id.startsWith("adzuna:");

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/40 backdrop-blur-2xs animate-in fade-in duration-150"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl max-h-[90dvh] flex flex-col rounded-xl border border-zinc-200 bg-white shadow-xl overflow-hidden"
      >
        {/* Modal Header */}
        <div className="flex items-start justify-between p-4 sm:p-6 border-b border-zinc-100">
          <div className="space-y-1 pr-4 min-w-0">
            <div className="flex flex-wrap items-center gap-1.5 sm:gap-2 text-[11px] sm:text-xs text-zinc-500">
              <span className="font-semibold text-zinc-900">{job.company}</span>
              <span>•</span>
              <span className="truncate">{job.location}</span>
            </div>
            <h2 className="text-base sm:text-lg font-semibold tracking-tight text-zinc-900 leading-snug">
              {job.title}
            </h2>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {isExactMatch ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-[11px] sm:text-xs font-semibold text-emerald-800">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                <span>Exact Match · {job.matchScore}%</span>
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-200 bg-zinc-100 px-2.5 py-0.5 text-[11px] sm:text-xs font-semibold text-zinc-700">
                <span className="h-1.5 w-1.5 rounded-full bg-zinc-400" />
                <span>Broader Fit · {job.matchScore}%</span>
              </span>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors"
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
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* Modal Scrollable Body */}
        <div className="p-4 sm:p-6 overflow-y-auto space-y-5">
          {/* Grounded AI Match Analysis Card */}
          {explanation && (
            <div className="rounded-xl border border-zinc-200/90 bg-zinc-50/80 p-4 space-y-2">
              <div className="flex items-center gap-1.5">
                <svg className="h-3.5 w-3.5 text-zinc-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>
                <h3 className="text-xs font-semibold tracking-wide uppercase text-zinc-800">
                  AI Match Analysis
                </h3>
              </div>
              <p className="text-xs sm:text-[13px] text-zinc-800 leading-relaxed font-normal">
                {explanation}
              </p>
            </div>
          )}

          {/* Strengths & Gaps (Green Strengths, Greyed Gaps) */}
          <div className="space-y-4">
            {/* Strengths (Green) */}
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                <h4 className="text-xs font-semibold text-zinc-900">
                  Strengths & Verified Matches ({strengths.length})
                </h4>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {strengths.length > 0 ? (
                  strengths.map((skill) => (
                    <span
                      key={skill}
                      className="rounded-md bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 text-xs font-medium text-emerald-800"
                    >
                      {skill}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-zinc-400 italic">No direct explicit skill overlap</span>
                )}
              </div>
            </div>

            {/* Gaps (Greyed out) */}
            {gaps.length > 0 && (
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <span className="h-2 w-2 rounded-full bg-zinc-400" />
                  <h4 className="text-xs font-semibold text-zinc-700">
                    Gaps & Missing Requirements ({gaps.length})
                  </h4>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {gaps.map((skill) => (
                    <span
                      key={skill}
                      className="rounded-md bg-zinc-100 border border-zinc-200/80 border-dashed px-2.5 py-0.5 text-xs font-medium text-zinc-500"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Itemized Deductions (if any) */}
          {deductions.length > 0 && (
            <div className="rounded-xl border border-zinc-200 bg-white p-3.5 space-y-2">
              <div className="flex items-center gap-1.5 text-zinc-800">
                <svg className="h-3.5 w-3.5 text-zinc-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-700">
                  Calibrated Deductions
                </h4>
              </div>
              <ul className="space-y-1.5 pl-5 list-disc text-xs text-zinc-600">
                {deductions.map((d, idx) => (
                  <li key={idx} className="leading-snug">
                    <span className="font-semibold text-zinc-900">-{d.points} pts:</span> {d.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Job Description Overview */}
          <div className="space-y-2 pt-3 border-t border-zinc-100">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-zinc-900">Job Overview</h4>
              {isAggregatorSnippet && (
                <span className="text-[10px] text-zinc-400 font-mono tracking-tight">
                  Aggregator preview snippet
                </span>
              )}
            </div>
            <div className="rounded-lg bg-zinc-50 p-3.5 text-xs text-zinc-600 leading-relaxed whitespace-pre-line max-h-60 overflow-y-auto border border-zinc-200/50 space-y-2.5">
              <p>
                {cleanedDescription}
                {isAggregatorSnippet ? "..." : ""}
              </p>
              {isAggregatorSnippet && (
                <p className="text-[11px] text-zinc-500 font-medium pt-2 border-t border-zinc-200/60">
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:text-blue-700 hover:underline inline-flex items-center gap-1 font-semibold"
                  >
                    Click &apos;Apply on Company Site&apos; to view the full job description
                    <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                      <polyline points="15 3 21 3 21 9" />
                    </svg>
                  </a>
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Modal Footer Actions */}
        <div className="flex items-center justify-end gap-2.5 p-3.5 sm:p-4 border-t border-zinc-100 bg-zinc-50">
          <Button variant="outline" className="w-auto h-8 sm:h-9 text-xs" onClick={onClose}>
            Close
          </Button>
          <Button
            className="w-auto h-8 sm:h-9 text-xs gap-1.5"
            onClick={() => window.open(job.url, "_blank", "noopener,noreferrer")}
          >
            <span>Apply on Company Site</span>
            <svg
              className="h-3 w-3"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
            </svg>
          </Button>
        </div>
      </div>
    </div>
  );
}
