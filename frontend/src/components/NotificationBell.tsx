"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppNotification, api } from "@/lib/api";

/**
 * The bell in the top bar — where Kafka's job matches actually surface.
 *
 * In-app rather than email, and that is a design decision worth defending. The match
 * consumer fires once per matching posting, so a night where the pipeline finds 200
 * relevant jobs would send 200 emails: the same information delivered in the most
 * annoying possible way, and a fast route to being marked as spam. A badge reading "12"
 * is the same content at a glance, needs no SMTP provider or deliverability setup, and
 * lives inside the product rather than in an inbox nobody opens.
 *
 * Polling, not websockets. New matches arrive when the pipeline runs — roughly daily —
 * so a socket would hold a connection open all day to deliver one burst. A 60-second poll
 * of an endpoint that returns a single integer is the cheaper, simpler answer, and the
 * right one until the data actually changes by the second.
 */
const POLL_MS = 60_000;

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const refreshCount = useCallback(async () => {
    try {
      const { unread } = await api.unreadCount();
      setUnread(unread);
    } catch {
      // A failed poll is not worth showing anyone. The next one is 60 seconds away, and
      // the bell going blank because the network hiccuped would be worse than a stale count.
    }
  }, []);

  useEffect(() => {
    refreshCount();
    const timer = setInterval(refreshCount, POLL_MS);
    return () => clearInterval(timer);
  }, [refreshCount]);

  // Close on an outside click or Escape — expected of any dropdown, and conspicuous when
  // missing.
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function toggle() {
    const next = !open;
    setOpen(next);
    // Fetch the list only when the panel opens. The badge needs a number; the rows are
    // payload nobody has asked to see yet.
    if (next) {
      setLoading(true);
      try {
        setItems(await api.listNotifications());
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }
  }

  async function markAllRead() {
    // Update the badge immediately rather than waiting for the request. Marking as read is
    // safe to be optimistic about: the worst case is a badge that reappears on the next
    // poll, which is far better than a button that appears to do nothing for 300ms.
    setUnread(0);
    setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    try {
      await api.markAllRead();
    } catch {
      refreshCount();
    }
  }

  async function openItem(n: AppNotification) {
    if (!n.read) {
      setUnread((u) => Math.max(0, u - 1));
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
      api.markRead(n.id).catch(() => refreshCount());
    }
    if (n.link) window.open(n.link, "_blank", "noopener,noreferrer");
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={toggle}
        aria-label={unread ? `${unread} unread notifications` : "Notifications"}
        aria-haspopup="menu"
        aria-expanded={open}
        className="relative flex h-9 w-9 items-center justify-center rounded-full text-zinc-600 transition hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
      >
        {/* Inline SVG, consistent with the charts — no icon library for one glyph. */}
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-medium text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-30 mt-2 w-96 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5 dark:border-zinc-800">
            <span className="text-sm font-medium">Notifications</span>
            {unread > 0 && (
              <button
                onClick={markAllRead}
                className="text-xs text-zinc-500 underline-offset-2 hover:underline"
              >
                Mark all read
              </button>
            )}
          </div>

          <div className="max-h-96 overflow-y-auto">
            {loading && <p className="px-4 py-6 text-center text-xs text-zinc-500">Loading…</p>}

            {!loading && items.length === 0 && (
              <div className="px-4 py-8 text-center">
                <p className="text-sm text-zinc-500">Nothing yet.</p>
                <p className="mt-1 text-xs text-zinc-400">
                  New job matches appear here after the pipeline runs.
                </p>
              </div>
            )}

            {items.map((n) => (
              <button
                key={n.id}
                onClick={() => openItem(n)}
                className={`block w-full border-b border-zinc-100 px-4 py-3 text-left transition last:border-0 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/50 ${
                  n.read ? "" : "bg-blue-50/50 dark:bg-blue-950/20"
                }`}
              >
                <div className="flex items-start gap-2">
                  {!n.read && (
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600" />
                  )}
                  <div className={n.read ? "pl-3.5" : ""}>
                    <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                      {n.title}
                    </p>
                    {n.body && (
                      <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">{n.body}</p>
                    )}
                    <p className="mt-1 text-[11px] text-zinc-400">
                      {new Date(n.created_at).toLocaleString()}
                      {n.link && " · opens the posting"}
                    </p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
