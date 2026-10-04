"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AuthCard } from "@/components/auth/auth-card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";

export default function AuthPage() {
  const router = useRouter();
  const supabase = createClient();

  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setInfoMessage(null);
    setLoading(true);

    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({
          email,
          password,
        });

        if (error) {
          setErrorMessage(error.message);
        } else {
          router.push("/dashboard");
          router.refresh();
        }
      } else {
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
        });

        if (error) {
          setErrorMessage(error.message);
        } else if (data.session) {
          router.push("/dashboard");
          router.refresh();
        } else {
          setInfoMessage("Verification email sent. Please check your inbox.");
        }
      }
    } catch {
      setErrorMessage("An unexpected authentication error occurred.");
    } finally {
      setLoading(false);
    }
  };

  const title = mode === "signin" ? "Sign in to Job Matcher" : "Create an account";
  const description =
    mode === "signin"
      ? "Enter your credentials to access your saved matches."
      : "Sign up to upload your resume and discover matches.";

  const footer =
    mode === "signin" ? (
      <span>
        Don&apos;t have an account?{" "}
        <button
          type="button"
          onClick={() => {
            setMode("signup");
            setErrorMessage(null);
            setInfoMessage(null);
          }}
          className="font-medium text-zinc-900 underline underline-offset-4 hover:text-zinc-700"
        >
          Sign up
        </button>
      </span>
    ) : (
      <span>
        Already have an account?{" "}
        <button
          type="button"
          onClick={() => {
            setMode("signin");
            setErrorMessage(null);
            setInfoMessage(null);
          }}
          className="font-medium text-zinc-900 underline underline-offset-4 hover:text-zinc-700"
        >
          Sign in
        </button>
      </span>
    );

  return (
    <AuthCard title={title} description={description} footer={footer}>
      <form onSubmit={handleSubmit} className="space-y-4">
        {errorMessage && (
          <div className="rounded-md border border-red-200 bg-red-50 p-2.5 text-xs text-red-700">
            {errorMessage}
          </div>
        )}

        {infoMessage && (
          <div className="rounded-md border border-zinc-200 bg-zinc-50 p-2.5 text-xs text-zinc-800">
            {infoMessage}
          </div>
        )}

        <Input
          label="Email address"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="name@example.com"
        />

        <Input
          label="Password"
          type="password"
          name="password"
          autoComplete={mode === "signin" ? "current-password" : "new-password"}
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
        />

        <Button type="submit" isLoading={loading}>
          {mode === "signin" ? "Continue with Email" : "Create Account"}
        </Button>
      </form>
    </AuthCard>
  );
}
