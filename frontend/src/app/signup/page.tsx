"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AuthLayout, { buttonClass, fieldClass, labelClass } from "@/components/AuthLayout";
import { api, ApiError } from "@/lib/api";

const MIN_PASSWORD_LENGTH = 8;

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      // Signup issues the same cookies as login, so there's no second step.
      await api.signup(email, password);
      router.push("/profile");   // straight to profile: it's what drives everything else
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Track applications, match your resume, and see what the job market actually pays."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-zinc-900 underline dark:text-zinc-100">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="email" className={labelClass}>
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={fieldClass}
          />
        </div>

        <div>
          <label htmlFor="password" className={labelClass}>
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={MIN_PASSWORD_LENGTH}
            autoComplete="new-password"
            placeholder="At least 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={fieldClass}
            aria-describedby="password-hint"
          />
          {/* Show the requirement while typing rather than only on submit — a rule you
              learn by failing is a bad rule. */}
          <p
            id="password-hint"
            className={`mt-1.5 text-xs ${tooShort ? "text-red-600" : "text-zinc-500"}`}
          >
            {tooShort
              ? `${MIN_PASSWORD_LENGTH - password.length} more character${
                  MIN_PASSWORD_LENGTH - password.length === 1 ? "" : "s"
                } needed`
              : "Minimum 8 characters. Stored hashed with bcrypt — never in plain text."}
          </p>
        </div>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
          >
            {error}
          </div>
        )}

        <button type="submit" disabled={loading || tooShort} className={buttonClass}>
          {loading ? "Creating account…" : "Create account"}
        </button>
      </form>
    </AuthLayout>
  );
}
