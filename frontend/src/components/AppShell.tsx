"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { api, User } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/jobs", label: "Jobs" },
  { href: "/resume", label: "Resume" },
  { href: "/applications", label: "Applications" },
  { href: "/analytics", label: "Analytics" },
  { href: "/copilot", label: "AI Copilot" },
];

/**
 * Wraps every signed-in page: session check, nav, and the account menu.
 *
 * The session check here is a UX convenience only — real enforcement is server-side in
 * the gateway's AuthMiddleware. A client-side route guard can always be bypassed by
 * editing JS in the browser, so it must never be the only thing between a user and
 * someone else's data.
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => router.push("/login"))
      .finally(() => setChecking(false));
  }, [router]);

  // Close the menu on an outside click or Escape — both expected of any dropdown, and
  // their absence is immediately noticeable.
  useEffect(() => {
    if (!menuOpen) return;
    function onClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  async function handleLogout() {
    await api.logout().catch(() => {});
    router.push("/login");
  }

  if (checking) {
    return <div className="p-10 text-sm text-zinc-500">Checking session…</div>;
  }
  if (!user) return null; // redirect already in flight

  const initial = user.email[0]?.toUpperCase() ?? "?";

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-6">
            <Link href="/dashboard" className="font-semibold tracking-tight">
              CareerLens
            </Link>
            <nav className="hidden gap-1 md:flex">
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

          {/* account menu — an avatar rather than a raw email string, which was both
              cluttered and leaked the address to anyone glancing at the screen */}
          <div className="relative" ref={menuRef}>
            <button
              onClick={() => setMenuOpen((v) => !v)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label="Account menu"
              className="flex h-9 w-9 items-center justify-center rounded-full bg-zinc-900 text-sm font-medium text-white transition hover:opacity-90 dark:bg-white dark:text-zinc-900"
            >
              {initial}
            </button>

            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 mt-2 w-56 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
              >
                <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
                  <div className="truncate text-sm font-medium">{user.email}</div>
                  <div className="mt-0.5 text-xs text-zinc-500">{user.role}</div>
                </div>

                <Link
                  href="/profile"
                  onClick={() => setMenuOpen(false)}
                  className="block px-4 py-2 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800"
                >
                  Profile & preferences
                </Link>
                <Link
                  href="/resume"
                  onClick={() => setMenuOpen(false)}
                  className="block px-4 py-2 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800"
                >
                  My resume
                </Link>

                <button
                  onClick={handleLogout}
                  className="w-full border-t border-zinc-100 px-4 py-2 text-left text-sm text-red-600 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800"
                >
                  Log out
                </button>
              </div>
            )}
          </div>
        </div>

        {/* nav wraps to a second row on small screens instead of overflowing */}
        <nav className="flex gap-1 overflow-x-auto border-t border-zinc-100 px-6 py-2 md:hidden dark:border-zinc-800">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`whitespace-nowrap rounded px-3 py-1.5 text-sm ${
                pathname === item.href
                  ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                  : "text-zinc-600 dark:text-zinc-400"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-8">{children}</main>
    </div>
  );
}
