"use client";

import * as React from "react";

export interface FileDropzoneProps {
  accept?: string;
  maxSizeMB?: number;
  selectedFile: File | null;
  onFileSelect: (file: File) => void;
  onRemoveFile: () => void;
  error?: string | null;
}

export function FileDropzone({
  accept = ".pdf,.docx",
  maxSizeMB = 5,
  selectedFile,
  onFileSelect,
  onRemoveFile,
  error,
}: FileDropzoneProps) {
  const [isDragging, setIsDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      onFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      onFileSelect(e.target.files[0]);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="w-full space-y-3">
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={handleFileChange}
        className="hidden"
        id="file-dropzone-input"
      />

      {!selectedFile ? (
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={`flex flex-col items-center justify-center rounded-lg border border-dashed p-6 sm:p-8 text-center cursor-pointer transition-colors ${
            isDragging
              ? "border-zinc-900 bg-zinc-100/70"
              : "border-zinc-300 bg-zinc-50/50 hover:border-zinc-400 hover:bg-zinc-50"
          }`}
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-md border border-zinc-200 bg-white mb-3">
            <svg
              className="h-4 w-4 text-zinc-600"
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
              <line x1="12" y1="18" x2="12" y2="12" />
              <line x1="9" y1="15" x2="15" y2="15" />
            </svg>
          </div>
          <p className="text-xs sm:text-sm font-medium text-zinc-900">
            Click to upload or drag and drop
          </p>
          <p className="mt-1 text-[11px] sm:text-xs text-zinc-500">
            PDF or DOCX (up to {maxSizeMB}MB)
          </p>
        </div>
      ) : (
        <div className="flex items-center justify-between rounded-lg border border-zinc-200 bg-zinc-50/60 p-3 sm:p-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-zinc-200 bg-white">
              <svg
                className="h-4 w-4 text-zinc-600"
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
              </svg>
            </div>
            <div className="min-w-0">
              <p className="truncate text-xs sm:text-sm font-medium text-zinc-900">
                {selectedFile.name}
              </p>
              <p className="text-[11px] text-zinc-500">
                {formatFileSize(selectedFile.size)}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onRemoveFile}
            className="ml-3 shrink-0 text-xs font-medium text-zinc-500 hover:text-zinc-900 transition-colors"
          >
            Remove
          </button>
        </div>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
