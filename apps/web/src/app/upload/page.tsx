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
      return;
    }

    if (selected.size > 5 * 1024 * 1024) {
      setError("File exceeds maximum allowed size of 5MB.");
      return;
    }

    setError(null);
    setFile(selected);
  };

  const handleRemove = () => {
    setFile(null);
    setError(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    // Dead UI interaction hook
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
          <FileDropzone
            selectedFile={file}
            onFileSelect={handleFileSelect}
            onRemoveFile={handleRemove}
            error={error}
          />

          <Button type="submit" disabled={!file}>
            Continue to Matching
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
