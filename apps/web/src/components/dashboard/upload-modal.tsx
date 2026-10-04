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
  const [uploading, setUploading] = React.useState(false);

  React.useEffect(() => {
    if (!open) {
      setFile(null);
      setError(null);
      setUploading(false);
    }
  }, [open]);

  if (!open) return null;

  const handleFileSelect = (selected: File) => {
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
    if (!file || uploading) return;

    setUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch("/api/backend/resumes/upload", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        const errorDetail =
          data?.detail?.message ||
          data?.detail ||
          data?.error ||
          "Validation failed. Please ensure your file is a valid resume.";
        setError(typeof errorDetail === "string" ? errorDetail : JSON.stringify(errorDetail));
      } else {
        onClose();
        if (onUploadSuccess) {
          onUploadSuccess();
        }
      }
    } catch {
      setError("Network or proxy error: Unable to connect to backend service.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      role="presentation"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-3.5 sm:p-4 animate-in fade-in duration-150"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-modal-title"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[440px] rounded-xl border border-zinc-200 bg-white p-5 sm:p-6 shadow-xl animate-in zoom-in-95 duration-150 relative space-y-4"
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
                Upload Resume
              </h2>
              <p className="text-[11px] text-zinc-500">
                PDF or DOCX • Replaces previous active resume
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="flex h-7 w-7 items-center justify-center rounded-md text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors cursor-pointer"
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

        {/* Upload Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 p-2.5 text-xs text-red-700 leading-relaxed">
              {error}
            </div>
          )}

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
              isLoading={uploading}
              className="w-auto h-8 px-3.5 text-xs"
            >
              {uploading ? "Validating & Saving..." : "Save Resume"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
