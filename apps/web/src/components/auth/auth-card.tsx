import * as React from "react";

export interface AuthCardProps {
  title: string;
  description: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function AuthCard({
  title,
  description,
  children,
  footer,
}: AuthCardProps) {
  return (
    <div className="flex min-h-dvh w-full items-center justify-center p-4 sm:p-6 md:p-8">
      <div className="w-full max-w-[380px] rounded-xl border border-zinc-200 bg-white p-6 sm:p-8 shadow-xs">
        {/* Brand Mark Header */}
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
              <rect width="20" height="14" x="2" y="7" rx="2" ry="2" />
              <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
            </svg>
          </div>
        </div>

        {/* Heading Block */}
        <div className="mb-6 text-center">
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
            {title}
          </h1>
          <p className="mt-1.5 text-xs text-zinc-500">{description}</p>
        </div>

        {/* Content / Form */}
        <div>{children}</div>

        {/* Optional Footer */}
        {footer && (
          <div className="mt-6 text-center text-xs text-zinc-500">{footer}</div>
        )}
      </div>
    </div>
  );
}
