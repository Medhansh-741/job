"use client";

import * as React from "react";
import { useRouter, usePathname } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onOpenUpload?: () => void;
}

export function Sidebar({
  collapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
  onOpenUpload,
}: SidebarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const supabase = createClient();

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    router.push("/");
    router.refresh();
  };

  const navigateTo = (path: string) => {
    onCloseMobile();
    router.push(path);
  };

  const navItems = [
    {
      label: "Matched Jobs",
      href: "/dashboard",
      icon: (
        <svg
          className="h-4 w-4 shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect width="20" height="14" x="2" y="7" rx="2" ry="2" />
          <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
        </svg>
      ),
    },
    {
      label: "My Resume",
      href: "/resume",
      icon: (
        <svg
          className="h-4 w-4 shrink-0"
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
      ),
    },
  ];

  const sidebarContent = (isMobileView: boolean) => (
    <div className="flex h-full flex-col justify-between p-3">
      {/* Top Section */}
      <div className="space-y-4">
        {/* Brand glyph / Logo: Clicking toggles collapse/expand */}
        <div className="flex items-center justify-between px-1">
          <button
            type="button"
            onClick={!isMobileView ? onToggleCollapse : undefined}
            title={!isMobileView ? (collapsed ? "Expand sidebar" : "Collapse sidebar") : undefined}
            className={`flex items-center gap-2.5 text-left rounded-lg p-0.5 transition-colors ${
              !isMobileView ? "hover:bg-zinc-100 cursor-pointer" : ""
            }`}
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-200 bg-zinc-50 shrink-0">
              <svg
                className="h-4 w-4 text-zinc-900"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect width="20" height="14" x="2" y="7" rx="2" ry="2" />
                <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
              </svg>
            </div>
            {(isMobileView || !collapsed) && (
              <span className="text-xs font-semibold text-zinc-900 tracking-tight truncate">
                Job Matcher
              </span>
            )}
          </button>

          {/* Close button on mobile drawer */}
          {isMobileView && (
            <button
              type="button"
              onClick={onCloseMobile}
              className="rounded-md p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100"
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
          )}
        </div>

        {/* Upload Action */}
        <div className="pt-1">
          <button
            type="button"
            onClick={() => {
              onCloseMobile();
              if (onOpenUpload) {
                onOpenUpload();
              } else {
                navigateTo("/resume");
              }
            }}
            title="Upload new resume"
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 p-2 text-xs font-medium text-zinc-900 hover:bg-zinc-100 hover:border-zinc-300 transition-colors"
          >
            <svg
              className="h-4 w-4 shrink-0 text-zinc-700"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            {(isMobileView || !collapsed) && <span className="truncate">Upload Resume</span>}
          </button>
        </div>

        {/* Navigation Items */}
        <nav className="space-y-1 pt-1">
          {navItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <button
                key={item.href}
                type="button"
                onClick={() => navigateTo(item.href)}
                title={item.label}
                className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs font-medium transition-colors ${
                  isActive
                    ? "bg-zinc-100 text-zinc-900"
                    : "text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900"
                }`}
              >
                {item.icon}
                {(isMobileView || !collapsed) && (
                  <span className="truncate">{item.label}</span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Sign Out Button */}
      <div className="border-t border-zinc-100 pt-2">
        <button
          type="button"
          onClick={handleSignOut}
          title="Sign out"
          className="flex w-full items-center justify-center gap-2 rounded-md p-2 text-xs text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 transition-colors"
        >
          <svg
            className="h-4 w-4 shrink-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
          {(isMobileView || !collapsed) && <span className="truncate">Sign out</span>}
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile Drawer (Only on < md) */}
      {mobileOpen && (
        <div
          role="presentation"
          onClick={onCloseMobile}
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-2xs md:hidden animate-in fade-in duration-200"
        />
      )}
      <div
        className={`fixed inset-y-0 left-0 z-50 w-64 bg-white shadow-xl md:hidden transform transition-transform duration-200 ease-in-out ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {sidebarContent(true)}
      </div>

      {/* Desktop Persistent Sidebar (Only on >= md) */}
      <aside
        className={`hidden md:flex md:sticky md:top-0 h-screen flex-col border-r border-zinc-200 bg-white transition-all duration-200 shrink-0 ${
          collapsed ? "w-16" : "w-56"
        }`}
      >
        {sidebarContent(false)}
      </aside>
    </>
  );
}
