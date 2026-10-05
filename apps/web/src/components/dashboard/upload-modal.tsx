"use client";

import * as React from "react";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { Button } from "@/components/ui/button";

export interface UploadModalProps {
  open: boolean;
  onClose: () => void;
  onUploadSuccess?: () => void;
}

export function UploadModal({
  open,
  onClose,
  onUploadSuccess,
}: UploadModalProps) {
  const [file, setFile] = React.useState<File | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [isProcessing, setIsProcessing] = React.useState(false);
  const [progress, setProgress] = React.useState<number>(0);
  const [stepLabel, setStepLabel] = React.useState<string>("");
  const [lockedWarning, setLockedWarning] = React.useState(false);

  const pollIntervalRef = React.useRef<NodeJS.Timeout | null>(null);
  const warningTimeoutRef = React.useRef<NodeJS.Timeout | null>(null);

  // Reset state when modal is closed
  React.useEffect(() => {
    if (!open) {
      setFile(null);
      setError(null);
      setIsProcessing(false);
      setProgress(0);
      setStepLabel("");
      setLockedWarning(false);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    }
  }, [open]);

  // Clean up timers on unmount
  React.useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (warningTimeoutRef.current) clearTimeout(warningTimeoutRef.current);
    };
  }, []);

  // Visual lock feedback when user tries to close while processing
  const triggerLockWarning = React.useCallback(() => {
    setLockedWarning(true);
    if (warningTimeoutRef.current) clearTimeout(warningTimeoutRef.current);
    warningTimeoutRef.current = setTimeout(() => {
      setLockedWarning(false);
    }, 2500);
  }, []);

  // Intercept Escape key during active processing
  React.useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (isProcessing) {
          e.preventDefault();
          e.stopPropagation();
          triggerLockWarning();
        } else {
          onClose();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, isProcessing, onClose, triggerLockWarning]);

  // Warn user before closing or reloading tab during active processing
  React.useEffect(() => {
    if (!isProcessing) return;
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isProcessing]);

  if (!open) return null;

  const handleBackdropClick = () => {
    if (isProcessing) {
      triggerLockWarning();
      return;
    }
    onClose();
  };

  const handleFileSelect = (selected: File) => {
    if (isProcessing) return;

    const validExtensions = [".pdf", ".docx"];
    const hasValidExt = validExtensions.some((ext) =>
      selected.name.toLowerCase().endsWith(ext)
    );

    if (!hasValidExt) {
      setError("Please select a valid PDF or DOCX file.");
      setFile(null);
      return;
    }

    if (selected.size === 0) {
      setError("The selected file is empty (0 bytes).");
      setFile(null);
      return;
    }

    if (selected.size > 5 * 1024 * 1024) {
      setError("File exceeds maximum allowed size of 5MB.");
      setFile(null);
      return;
    }

    setError(null);
    setFile(selected);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || isProcessing) return;

    setIsProcessing(true);
    setError(null);
    setProgress(15);
    setStepLabel("Validating document and uploading file...");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch("/api/backend/resumes/upload", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        setIsProcessing(false);
        const errorDetail =
          data?.detail?.message ||
          data?.detail ||
          data?.error ||
          "Validation failed. Please ensure your file is a valid resume.";
        setError(typeof errorDetail === "string" ? errorDetail : JSON.stringify(errorDetail));
        return;
      }

      // Resume uploaded successfully. Advance progress and begin live sync polling
      setProgress(40);
      setStepLabel("Resume saved. Initializing matching pipeline...");

      let pollAttempts = 0;
      const maxAttempts = 96; // 96 * 500ms = 48s circuit breaker

      pollIntervalRef.current = setInterval(async () => {
        pollAttempts++;
        if (pollAttempts > maxAttempts) {
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          setIsProcessing(false);
          setError("Matching is taking longer than expected. Please check your dashboard in a moment.");
          return;
        }

        try {
          const statusRes = await fetch("/api/backend/matches/status");
          if (statusRes.ok) {
            const statusData = await statusRes.json();

            if (statusData.status === "processing") {
              // Ensure monotonic forward progress
              setProgress((prev) => Math.max(prev, statusData.progress || 40));
              if (statusData.step_label) {
                setStepLabel(statusData.step_label);
              }
            } else if (statusData.status === "completed") {
              if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
              setProgress(100);
              // The AI step can finish late (rate limit / slow service): say so instead of claiming matches are ready
              const aiStillPending = Boolean(statusData.analysis_pending);
              setStepLabel(
                aiStillPending
                  ? "Resume saved. The AI service is slow right now, so your matches will appear on the dashboard shortly."
                  : "Matches ready! Loading your dashboard..."
              );

              // Brief hold so the message registers; a little longer when the user needs to read the delay notice
              setTimeout(() => {
                setIsProcessing(false);
                onClose();
                if (onUploadSuccess) {
                  onUploadSuccess();
                }
              }, aiStillPending ? 1600 : 250);
            } else if (statusData.status === "failed") {
              if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
              setIsProcessing(false);
              setError(statusData.error || "Matching pipeline encountered an issue. Please try again.");
            }
          }
        } catch (err) {
          // Gracefully continue on temporary network blips
          console.warn("Matching status poll hiccup, retrying...", err);
        }
      }, 500);
    } catch {
      setIsProcessing(false);
      setError("Network or proxy error: Unable to connect to backend service.");
    }
  };

  return (
    <div
      role="presentation"
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-3.5 sm:p-4 animate-in fade-in duration-150"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-modal-title"
        onClick={(e) => e.stopPropagation()}
        className={`w-full max-w-[460px] rounded-xl border border-zinc-200 bg-white p-5 sm:p-6 shadow-xl animate-in zoom-in-95 duration-150 relative space-y-4 transition-all ${
          lockedWarning ? "ring-2 ring-amber-400 scale-[1.01]" : ""
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-200 bg-zinc-50">
              <svg
                className="h-4 w-4 text-zinc-900"
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
            <div>
              <h2 id="upload-modal-title" className="text-sm font-semibold text-zinc-900 tracking-tight">
                {isProcessing ? "Processing Resume" : "Upload Resume"}
              </h2>
              <p className="text-[11px] text-zinc-500">
                {isProcessing
                  ? "Evaluating profile against job catalog"
                  : "PDF or DOCX • Replaces previous active resume"}
              </p>
            </div>
          </div>

          {/* Close button: hidden / disabled during processing */}
          <button
            type="button"
            onClick={isProcessing ? triggerLockWarning : onClose}
            disabled={isProcessing}
            aria-label="Close dialog"
            className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors ${
              isProcessing
                ? "text-zinc-300 cursor-not-allowed"
                : "text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 cursor-pointer"
            }`}
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

        {/* Lock Warning Notice */}
        {lockedWarning && isProcessing && (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-800 flex items-center gap-2 animate-in fade-in duration-100">
            <svg className="h-4 w-4 text-amber-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>Please wait—matching is currently processing your resume.</span>
          </div>
        )}

        {/* Error Notice */}
        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 p-2.5 text-xs text-red-700 leading-relaxed">
            {error}
          </div>
        )}

        {/* Live Processing Progress Bar View */}
        {isProcessing ? (
          <div className="space-y-4 py-3">
            <div className="rounded-xl border border-zinc-200 bg-zinc-50/70 p-4 space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-zinc-900 flex items-center gap-1.5">
                  <span className="inline-block h-2 w-2 rounded-full bg-emerald-500 animate-ping" />
                  Live Funnel Progress
                </span>
                <span className="font-mono font-semibold text-zinc-700 text-xs">
                  {progress}%
                </span>
              </div>

              {/* Progress Track */}
              <div className="w-full bg-zinc-200/80 rounded-full h-2 overflow-hidden">
                <div
                  className="h-full bg-zinc-900 rounded-full transition-all duration-500 ease-out"
                  style={{ width: `${progress}%` }}
                />
              </div>

              {/* Current Step Label */}
              <p className="text-xs text-zinc-600 min-h-[20px] transition-all">
                {stepLabel || "Analyzing candidate profile..."}
              </p>
            </div>

            <p className="text-[11px] text-zinc-400 text-center">
              Please keep this window open while AI matching finishes.
            </p>
          </div>
        ) : (
          /* Standard Upload Form */
          <form onSubmit={handleSubmit} className="space-y-4">
            <FileDropzone
              selectedFile={file}
              onFileSelect={handleFileSelect}
              onRemoveFile={() => {
                setFile(null);
                setError(null);
              }}
            />

            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={onClose}
                className="h-8 rounded-md border border-zinc-200 bg-white px-3 text-xs font-medium text-zinc-700 hover:bg-zinc-50 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <Button
                type="submit"
                disabled={!file}
                className="w-auto h-8 px-3.5 text-xs"
              >
                Upload & Match Roles
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
