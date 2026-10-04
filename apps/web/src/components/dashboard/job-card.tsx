"use client";

import * as React from "react";
import { Job } from "@/types/job";

export interface JobCardProps {
  job: Job;
  onSelect: (jobId: string) => void;
}

export function JobCard({ job, onSelect }: JobCardProps) {
  const handleApplyClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    window.open(job.url, "_blank", "noopener,noreferrer");
  };

  return (
    <div
      onClick={() => onSelect(job.id)}
      className="group relative cursor-pointer rounded-xl border border-zinc-200 bg-white p-3.5 sm:p-5 shadow-xs transition-all hover:border-zinc-300 hover:shadow-sm"
    >
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2.5">
        {/* Job Info */}
        <div className="space-y-1 min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5 sm:gap-2 text-[11px] sm:text-xs text-zinc-500">
            <span className="font-medium text-zinc-900">{job.company}</span>
            <span>•</span>
            <span className="truncate">{job.location}</span>
            {job.postedAt && (
              <>
                <span className="hidden sm:inline">•</span>
                <span className="hidden sm:inline">{job.postedAt}</span>
              </>
            )}
          </div>

          <h3 className="text-sm sm:text-base font-semibold tracking-tight text-zinc-900 group-hover:text-zinc-700 transition-colors leading-snug">
            {job.title}
          </h3>
        </div>

        {/* Match Score Badge */}
        <div className="shrink-0 flex items-center justify-between sm:justify-end gap-2">
          <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 sm:px-2.5 py-0.5 text-[11px] sm:text-xs font-medium text-emerald-800">
            {job.matchScore}% Match
          </span>
        </div>
      </div>

      {/* Skills & Action Footer */}
      <div className="mt-3 sm:mt-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pt-2.5 sm:pt-3 border-t border-zinc-100">
        {/* Skills Chips */}
        <div className="flex flex-wrap items-center gap-1 sm:gap-1.5">
          {job.matchedSkills.slice(0, 4).map((skill) => (
            <span
              key={skill}
              className="rounded bg-zinc-100 px-1.5 sm:px-2 py-0.5 text-[10px] sm:text-[11px] font-medium text-zinc-700"
            >
              {skill}
            </span>
          ))}
          {job.matchedSkills.length > 4 && (
            <span className="text-[10px] sm:text-[11px] text-zinc-400 font-medium">
              +{job.matchedSkills.length - 4}
            </span>
          )}
        </div>

        {/* Direct Apply Button */}
        <div className="shrink-0 flex justify-end">
          <button
            type="button"
            onClick={handleApplyClick}
            className="inline-flex items-center gap-1.5 rounded-md border border-zinc-300 bg-white px-2.5 sm:px-3 py-1 text-xs font-medium text-zinc-900 hover:bg-zinc-50 hover:border-zinc-400 transition-colors"
          >
            <span>Apply</span>
            <svg
              className="h-3 w-3 text-zinc-500"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
