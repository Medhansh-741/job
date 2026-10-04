"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/dashboard/sidebar";
import { UploadModal } from "@/components/dashboard/upload-modal";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { Button } from "@/components/ui/button";

interface ResumeItem {
  id: string;
  name: string;
  size: string;
  uploadedAt: string;
  downloadUrl: string | null;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ResumePage() {
  const router = useRouter();
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = React.useState(false);
  const [uploadModalOpen, setUploadModalOpen] = React.useState(false);

  const [activeResume, setActiveResume] = React.useState<ResumeItem | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Inline upload state for empty view
  const [inlineFile, setInlineFile] = React.useState<File | null>(null);
  const [inlineUploading, setInlineUploading] = React.useState(false);
  const [inlineError, setInlineError] = React.useState<string | null>(null);

  const fetchActiveResume = React.useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch("/api/backend/resumes/active");
      if (!res.ok) {
        if (res.status === 401) {
          router.push("/");
          return;
        }
        throw new Error("Failed to load active resume");
      }
      const data = await res.json();
      if (data?.active) {
        setActiveResume({
          id: data.active.id,
          name: data.active.filename,
          size: formatBytes(data.active.file_size || 0),
          uploadedAt: data.active.created_at
            ? new Date(data.active.created_at).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })
            : "Recently",
          downloadUrl: data.active.download_url,
        });
      } else {
        setActiveResume(null);
      }
    } catch {
      setError("Unable to connect to service to fetch resume.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  React.useEffect(() => {
    fetchActiveResume();
  }, [fetchActiveResume]);

  const handleDelete = async () => {
    try {
      setDeleting(true);
      setError(null);
      const res = await fetch("/api/backend/resumes/active", {
        method: "DELETE",
      });
      if (!res.ok) {
        throw new Error("Failed to delete resume");
      }
      setActiveResume(null);
      setConfirmDelete(false);
    } catch {
      setError("Failed to delete resume. Please try again.");
    } finally {
      setDeleting(false);
    }
  };

  const handleDownload = () => {
    if (!activeResume?.downloadUrl) {
      alert("Download URL is not available. Please refresh.");
      return;
    }
    window.open(activeResume.downloadUrl, "_blank", "noopener,noreferrer");
  };

  const handleInlineFileSelect = (file: File) => {
    const validExtensions = [".pdf", ".docx"];
    const hasValidExt = validExtensions.some((ext) =>
      file.name.toLowerCase().endsWith(ext)
    );

    if (!hasValidExt) {
      setInlineError("Please select a valid PDF or DOCX file.");
      setInlineFile(null);
      return;
    }

    if (file.size === 0) {
      setInlineError("The selected file is empty (0 bytes).");
      setInlineFile(null);
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      setInlineError("File exceeds maximum allowed size of 5MB.");
      setInlineFile(null);
      return;
    }

    setInlineError(null);
    setInlineFile(file);
  };

  const handleInlineUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inlineFile || inlineUploading) return;

    setInlineUploading(true);
    setInlineError(null);

    try {
      const formData = new FormData();
      formData.append("file", inlineFile);

      const res = await fetch("/api/backend/resumes/upload", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) {
        const msg = data?.detail?.message || data?.detail || "Validation failed";
        setInlineError(typeof msg === "string" ? msg : JSON.stringify(msg));
      } else {
        setInlineFile(null);
        await fetchActiveResume();
      }
    } catch {
      setInlineError("Network error: Unable to upload resume.");
    } finally {
      setInlineUploading(false);
    }
  };

  return (
    <div className="flex min-h-dvh bg-zinc-50">
      {/* Responsive Sidebar */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        mobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
        onOpenUpload={() => setUploadModalOpen(true)}
      />

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 w-full">
        {/* Top Header */}
        <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/95 backdrop-blur-xs px-3.5 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
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
            <h1 className="text-base font-semibold text-zinc-900 tracking-tight">
              My Resume
            </h1>
          </div>

          {activeResume && (
            <button
              type="button"
              onClick={() => setUploadModalOpen(true)}
              className="flex h-8 items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors cursor-pointer"
            >
              <svg
                className="h-3.5 w-3.5 text-zinc-600"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="12" y1="18" x2="12" y2="12" />
                <line x1="9" y1="15" x2="15" y2="15" />
              </svg>
              <span>Upload New</span>
            </button>
          )}
        </header>

        {/* Content Body */}
        <div className="flex-1 p-3.5 sm:p-5 md:p-6 max-w-4xl w-full mx-auto space-y-4">
          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              {error}
            </div>
          )}

          {loading ? (
            <div className="rounded-xl border border-zinc-200 bg-white p-8 sm:p-12 text-center text-xs text-zinc-400">
              Loading active resume...
            </div>
          ) : activeResume ? (
            /* Active Resume Card */
            <div className="rounded-xl border border-zinc-200 bg-white p-4 sm:p-5 shadow-xs space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                {/* File Info */}
                <div className="flex items-center gap-3.5 min-w-0">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-zinc-200 bg-zinc-50">
                    <svg
                      className="h-5 w-5 text-zinc-700"
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

                  <div className="min-w-0 space-y-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-semibold text-zinc-900">
                        {activeResume.name}
                      </p>
                      <span className="inline-flex items-center rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[10px] font-medium text-emerald-800">
                        Active
                      </span>
                    </div>
                    <p className="text-xs text-zinc-500">
                      {activeResume.size} • Uploaded on {activeResume.uploadedAt}
                    </p>
                  </div>
                </div>

                {/* Actions: Download & Delete */}
                <div className="flex items-center gap-2 shrink-0 self-end sm:self-auto">
                  {/* Download Action */}
                  <button
                    type="button"
                    title="Download resume"
                    onClick={handleDownload}
                    className="flex h-8 items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 hover:border-zinc-300 transition-colors cursor-pointer"
                  >
                    <svg
                      className="h-3.5 w-3.5 text-zinc-600"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                    <span>Download</span>
                  </button>

                  {/* Delete Action */}
                  {!confirmDelete ? (
                    <button
                      type="button"
                      title="Remove resume"
                      onClick={() => setConfirmDelete(true)}
                      className="flex h-8 items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 text-xs font-medium text-red-600 hover:bg-red-50 hover:border-red-200 transition-colors cursor-pointer"
                    >
                      <svg
                        className="h-3.5 w-3.5"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M3 6h18" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                        <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      </svg>
                      <span>Delete</span>
                    </button>
                  ) : (
                    <div className="flex items-center gap-1.5 animate-in fade-in duration-100">
                      <button
                        type="button"
                        onClick={handleDelete}
                        disabled={deleting}
                        className="h-8 rounded-md bg-red-600 px-2.5 text-xs font-medium text-white hover:bg-red-700 transition-colors cursor-pointer disabled:opacity-50"
                      >
                        {deleting ? "Deleting..." : "Confirm Delete"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDelete(false)}
                        disabled={deleting}
                        className="h-8 rounded-md border border-zinc-200 bg-white px-2 text-xs text-zinc-600 hover:bg-zinc-100 transition-colors cursor-pointer"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            /* Empty State with Integrated Dropzone */
            <div className="rounded-xl border border-zinc-200 bg-white p-6 sm:p-8 shadow-xs max-w-lg mx-auto space-y-5">
              <div className="text-center space-y-1">
                <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-lg border border-zinc-200 bg-zinc-50 text-zinc-700 mb-3">
                  <svg
                    className="h-5 w-5"
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
                <h3 className="text-base font-semibold text-zinc-900 tracking-tight">
                  No active resume uploaded
                </h3>
                <p className="text-xs text-zinc-500">
                  Upload your resume in PDF or DOCX format to calculate match scores and discover recommended positions.
                </p>
              </div>

              <form onSubmit={handleInlineUpload} className="space-y-4">
                {inlineError && (
                  <div className="rounded-md border border-red-200 bg-red-50 p-2.5 text-xs text-red-700 leading-relaxed">
                    {inlineError}
                  </div>
                )}

                <FileDropzone
                  selectedFile={inlineFile}
                  onFileSelect={handleInlineFileSelect}
                  onRemoveFile={() => {
                    setInlineFile(null);
                    setInlineError(null);
                  }}
                />

                <Button
                  type="submit"
                  disabled={!inlineFile}
                  isLoading={inlineUploading}
                  className="w-full h-9 text-xs"
                >
                  {inlineUploading ? "Validating & Storing..." : "Save Resume"}
                </Button>
              </form>
            </div>
          )}
        </div>
      </main>

      {/* Upload Modal (Triggered by Sidebar or Header) */}
      <UploadModal
        open={uploadModalOpen}
        onClose={() => setUploadModalOpen(false)}
        onUploadSuccess={fetchActiveResume}
      />
    </div>
  );
}
