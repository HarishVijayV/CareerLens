"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { api, User } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/jobs", label: "Jobs" },
  { href: "/analytics", label: "Analytics" },
  { href: "/copilot", label: "AI Copilot" },
  { href: "/profile", label: "Profile" },
];

/**
 * Wraps every signed-in page: checks the session once, renders the nav, handles logout.
 *
 * This check is a UX convenience only — the real enforcement is server-side in the
 * gateway's AuthMiddleware. Client-side route guards can always be bypassed by editing
 * JS in the browser, so they must never be the only thing standing between a user and
 * someone else's data.
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => router.push("/login"))
      .finally(() => setChecking(false));
  }, [router]);

  async function handleLogout() {
    await api.logout().catch(() => {});
    router.push("/login");
  }

  if (checking) {
    return <div className="p-10 text-sm text-zinc-500">Checking session…</div>;
  }
  if (!user) return null; // redirect already in flight

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-6">
            <span className="font-semibold">CareerLens</span>
            <nav className="flex gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded px-3 py-1.5 text-sm transition-colors ${
                    pathname === item.href
                      ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                      : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                  }`}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-zinc-500 sm:inline">{user.email}</span>
            <button
              onClick={handleLogout}
              className="rounded border border-zinc-300 px-3 py-1.5 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}
