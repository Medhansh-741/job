"use client";

import { useState } from "react";
import { AuthCard } from "@/components/auth/auth-card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export default function AuthPage() {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    // Wireframe interaction - ready for Supabase auth integration
    setTimeout(() => {
      setLoading(false);
    }, 600);
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
          onClick={() => setMode("signup")}
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
          onClick={() => setMode("signin")}
          className="font-medium text-zinc-900 underline underline-offset-4 hover:text-zinc-700"
        >
          Sign in
        </button>
      </span>
    );

  return (
    <AuthCard title={title} description={description} footer={footer}>
      <form onSubmit={handleSubmit} className="space-y-4">
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
          rightAction={
            mode === "signin" ? (
              <button
                type="button"
                className="text-xs text-zinc-500 hover:text-zinc-800 transition-colors"
              >
                Forgot password?
              </button>
            ) : undefined
          }
        />

        <Button type="submit" isLoading={loading}>
          {mode === "signin" ? "Continue with Email" : "Create Account"}
        </Button>
      </form>
    </AuthCard>
  );
}
