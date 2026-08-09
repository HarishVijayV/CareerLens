/**
 * One registry of in-flight assistant requests, shared by every page.
 *
 * Each page used to park its own promise in its own module variable, which handled
 * "navigate away and come back" and nothing else. Send a message on Resume, switch to
 * Assistant, switch back: the Resume page remounted, found its variable had been reset by
 * its own unmount/remount cycle, and showed no spinner and no answer — while the request
 * ran to completion on the server and, for a rewrite, saved a new version. A reply that
 * arrives nowhere reads as a failure of something that actually worked.
 *
 * Keyed by page, so Resume and Assistant can each have a request in flight at the same
 * time without either claiming the other's answer.
 *
 * Module scope survives client-side navigation because Next.js does not re-evaluate the
 * module — only a full page reload clears this, which is correct: that genuinely is a new
 * page and there is nothing left listening.
 *
 * Subscribers rather than a bare promise: a page that mounts mid-flight needs to know
 * there IS a request (to show the spinner) before it knows the answer, and more than one
 * component may care.
 */
import type { AgentAnswer } from "@/lib/api";

export type PendingKey = "assistant" | "resume";

type Listener = (result: AgentAnswer | Error) => void;

interface Pending {
  promise: Promise<AgentAnswer>;
  listeners: Set<Listener>;
  /** The message that started it, so a remounting page can show what is being worked on. */
  prompt: string;
}

const pending = new Map<PendingKey, Pending>();

/** Start a request and register it. Returns the promise so the caller can await it too. */
export function startRequest(
  key: PendingKey,
  prompt: string,
  run: () => Promise<AgentAnswer>
): Promise<AgentAnswer> {
  const promise = run();
  const entry: Pending = { promise, listeners: new Set(), prompt };
  pending.set(key, entry);

  const settle = (result: AgentAnswer | Error) => {
    // Delete BEFORE notifying: a listener that immediately starts another request must not
    // have its new entry wiped by this cleanup.
    if (pending.get(key) === entry) pending.delete(key);
    entry.listeners.forEach((listener) => listener(result));
    entry.listeners.clear();
  };

  promise
    .then(settle)
    .catch((e) => settle(e instanceof Error ? e : new Error(String(e))));

  return promise;
}

/** Whether a request is running, and what was asked — for restoring the spinner. */
export function getPending(key: PendingKey): { prompt: string } | null {
  const entry = pending.get(key);
  return entry ? { prompt: entry.prompt } : null;
}

/**
 * Attach to a running request. Returns an unsubscribe function, or null if none is
 * running. Safe to call on every mount.
 */
export function subscribe(key: PendingKey, listener: Listener): (() => void) | null {
  const entry = pending.get(key);
  if (!entry) return null;
  entry.listeners.add(listener);
  return () => entry.listeners.delete(listener);
}
