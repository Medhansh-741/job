"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";

export default function DashboardPage() {
  const router = useRouter();
  const supabase = createClient();
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<string | null>(null);
  const [loadingBackend, setLoadingBackend] = useState(false);

  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (!user) {
        router.push("/");
      } else {
        setUserEmail(user.email ?? "Authenticated User");
      }
    });
  }, [router, supabase]);

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    router.push("/");
    router.refresh();
  };

  const testBackendProxy = async () => {
    setLoadingBackend(true);
    try {
      const res = await fetch("/api/backend/me");
      const data = await res.json();
      setBackendStatus(JSON.stringify(data, null, 2));
    } catch {
      setBackendStatus("Failed to reach backend proxy");
    } finally {
      setLoadingBackend(false);
    }
  };

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center p-4 sm:p-6 bg-zinc-50">
      <div className="w-full max-w-md rounded-xl border border-zinc-200 bg-white p-6 sm:p-8 shadow-xs space-y-6">
        <div className="flex items-center justify-between border-b border-zinc-100 pb-4">
          <div>
            <h1 className="text-base font-semibold text-zinc-900">Dashboard</h1>
            <p className="text-xs text-zinc-500">{userEmail ?? "Loading session..."}</p>
          </div>
          <Button
            variant="outline"
            className="w-auto h-8 px-3 text-xs"
            onClick={handleSignOut}
          >
            Sign out
          </Button>
        </div>

        <div className="rounded-lg border border-zinc-100 bg-zinc-50 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-700">
              BFF Proxy Security Test
            </span>
            <Button
              className="w-auto h-8 px-3 text-xs"
              onClick={testBackendProxy}
              isLoading={loadingBackend}
            >
              Verify /api/backend/me
            </Button>
          </div>
          <p className="text-[11px] text-zinc-500 leading-relaxed">
            Tests client → Next.js Proxy → FastAPI with injected Bearer JWT.
          </p>
          {backendStatus && (
            <pre className="rounded bg-zinc-900 p-2 text-[11px] text-zinc-100 font-mono overflow-x-auto">
              {backendStatus}
            </pre>
          )}
        </div>
      </div>
    </main>
  );
}
