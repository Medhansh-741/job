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

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/40 backdrop-blur-2xs animate-in fade-in duration-150"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl max-h-[90dvh] flex flex-col rounded-xl border border-zinc-200 bg-white shadow-xl overflow-hidden"
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
            <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 sm:px-2.5 py-0.5 text-[11px] sm:text-xs font-medium text-emerald-800">
              {job.matchScore}% Match
            </span>
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
        <div className="p-4 sm:p-6 overflow-y-auto space-y-4 sm:space-y-5">
          {/* Why It Matches Section (Lazy LLM explanation container) */}
          <div className="rounded-lg border border-zinc-200 bg-zinc-50/70 p-3.5 sm:p-4 space-y-1.5">
            <div className="flex items-center justify-between">
              <h3 className="text-[11px] sm:text-xs font-semibold uppercase tracking-wider text-zinc-700">
                Why It Matches Your Profile
              </h3>
              <span className="text-[10px] text-zinc-400 font-mono">
                AI Evaluation
              </span>
            </div>
            <p className="text-xs text-zinc-600 leading-relaxed">
              Strong alignment across core requirements. Your experience with{" "}
              <strong className="text-zinc-900 font-medium">
                {job.matchedSkills.slice(0, 3).join(", ")}
              </strong>{" "}
              directly satisfies this position&apos;s technical qualifications.
            </p>
          </div>

          {/* Skills Breakdown */}
          <div className="space-y-2.5">
            <div>
              <h4 className="text-xs font-medium text-zinc-700 mb-1.5">
                Matched Skills ({job.matchedSkills.length})
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {job.matchedSkills.map((skill) => (
                  <span
                    key={skill}
                    className="rounded bg-emerald-50 border border-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </div>

            {job.missingSkills && job.missingSkills.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-zinc-500 mb-1.5">
                  Skills to Learn / Mention ({job.missingSkills.length})
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {job.missingSkills.map((skill) => (
                    <span
                      key={skill}
                      className="rounded bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-600"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Job Description Preview */}
          <div className="space-y-1.5 pt-2 border-t border-zinc-100">
            <h4 className="text-xs font-medium text-zinc-700">Role Overview</h4>
            <p className="text-xs text-zinc-600 leading-relaxed whitespace-pre-line">
              {job.description}
            </p>
          </div>
        </div>

        {/* Modal Footer Actions */}
        <div className="flex items-center justify-end gap-2.5 p-3 sm:p-4 border-t border-zinc-100 bg-zinc-50">
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
