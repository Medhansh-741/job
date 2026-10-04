"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";

export default function UploadPage() {
  const router = useRouter();
  const supabase = createClient();

  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    router.push("/");
    router.refresh();
  };

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
    setSuccessMessage(null);
    setFile(selected);
  };

  const handleRemove = () => {
    setFile(null);
    setError(null);
    setSuccessMessage(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || uploading) return;

    setUploading(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const formData = new FormData();
      formData.append("file", file);

      // Call BFF proxy endpoint -> forwards to FastAPI with user's JWT
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
        setSuccessMessage(
          `Resume successfully validated and stored (${data.characters_extracted} characters parsed).`
        );
      }
    } catch {
      setError("Network or proxy error: Unable to connect to backend service.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <main className="flex min-h-dvh items-center justify-center p-4 sm:p-6 bg-zinc-50">
      <div className="w-full max-w-[440px] rounded-xl border border-zinc-200 bg-white p-6 sm:p-8 shadow-xs relative">
        {/* Top Header Actions */}
        <div className="flex justify-end mb-2">
          <button
            type="button"
            onClick={handleSignOut}
            className="text-xs text-zinc-500 hover:text-zinc-900 transition-colors"
          >
            Sign out
          </button>
        </div>

        {/* Minimal Glyph */}
        <div className="mb-6 flex justify-center">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-zinc-200 bg-zinc-50">
            <svg
              className="h-5 w-5 text-zinc-900"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
              <polyline points="14 2 14 8 20 8" />
              <path d="M12 18v-6" />
              <path d="m9 15 3-3 3 3" />
            </svg>
          </div>
        </div>

        {/* Header */}
        <div className="mb-6 text-center">
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
            Upload Resume
          </h1>
          <p className="mt-1.5 text-xs text-zinc-500">
            Upload your resume in PDF or DOCX format to start matching.
          </p>
        </div>

        {/* Upload Form */}
        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700 leading-relaxed">
              {error}
            </div>
          )}

          {successMessage && (
            <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800 leading-relaxed">
              {successMessage}
            </div>
          )}

          <FileDropzone
            selectedFile={file}
            onFileSelect={handleFileSelect}
            onRemoveFile={handleRemove}
          />

          <Button type="submit" disabled={!file} isLoading={uploading}>
            {uploading ? "Validating & Storing..." : "Continue to Matching"}
          </Button>
        </form>

        {/* Security Note */}
        <p className="mt-5 text-center text-[11px] text-zinc-400">
          Your resume is analyzed securely and kept private to your account.
        </p>
      </div>
    </main>
  );
}
