/**
 * A mailbox for assistant requests, shared by every page.
 *
 * The problem this solves, in the order the bugs appeared:
 *
 * 1. The request lived inside the component, so navigating away destroyed the only thing
 *    awaiting it. The server finished the work — for a rewrite it even saved a new
 *    version — and the reply landed nowhere.
 *
 * 2. Moving the promise to module scope fixed navigating away and back, but each page had
 *    its own variable, so Resume -> Assistant -> Resume still lost answers.
 *
 * 3. A shared registry fixed that, and still dropped the common case: if the request
 *    COMPLETED while you were on another page, the entry was deleted on settle. Coming
 *    back found nothing pending, subscribed to nothing, and the answer was gone. That is
 *    the version that "didn't work in both places".
 *
 * So this is a MAILBOX, not a subscription list. A finished result is kept until someone
 * collects it, and only then discarded. A page mounting at any point — before, during, or
 * after the request — gets the answer.
 *
 * Keyed by page so Resume and Assistant can each have one in flight without either
 * claiming the other's. Module scope survives client-side navigation; a full page reload
 * clears it, which is correct, since nothing is left listening after a reload.
 */
import type { AgentAnswer } from "@/lib/api";

export type PendingKey = "assistant" | "resume";

type Result = AgentAnswer | Error;
type Listener = (result: Result) => void;

interface Entry {
  prompt: string;
  /** Set once the request finishes and cleared when a page collects it. */
  result?: Result;
  listeners: Set<Listener>;
}

const entries = new Map<PendingKey, Entry>();

/** Start a request and register it. The caller still gets the promise to await. */
export function startRequest(
  key: PendingKey,
  prompt: string,
  run: () => Promise<AgentAnswer>
): Promise<AgentAnswer> {
  const entry: Entry = { prompt, listeners: new Set() };
  entries.set(key, entry);

  const settle = (result: Result) => {
    if (entries.get(key) !== entry) return;   // superseded by a newer request

    if (entry.listeners.size > 0) {
      // Someone is listening right now — hand it over and close the mailbox.
      entry.listeners.forEach((listener) => listener(result));
      entry.listeners.clear();
      entries.delete(key);
    } else {
      // Nobody is mounted. HOLD the result rather than discarding it — this is the case
      // that used to lose answers, and it is the most common one, because the whole point
      // is that the user went somewhere else while it ran.
      entry.result = result;
    }
  };

  const promise = run();
  promise.then(settle).catch((e) => settle(e instanceof Error ? e : new Error(String(e))));
  return promise;
}

/** What state this key is in, for restoring the spinner on mount. */
export function getPending(key: PendingKey): { prompt: string; done: boolean } | null {
  const entry = entries.get(key);
  return entry ? { prompt: entry.prompt, done: entry.result !== undefined } : null;
}

/**
 * Collect the answer for a key: delivered immediately if it already finished, otherwise
 * when it does. Returns an unsubscribe function, or null if there is nothing to wait for.
 *
 * Safe to call on every mount — that is the point.
 */
export function subscribe(key: PendingKey, listener: Listener): (() => void) | null {
  const entry = entries.get(key);
  if (!entry) return null;

  if (entry.result !== undefined) {
    const result = entry.result;
    entries.delete(key);
    // Deliver asynchronously so the caller finishes mounting first — calling setState
    // synchronously inside an effect body that is still running is a React warning.
    queueMicrotask(() => listener(result));
    return null;
  }

  entry.listeners.add(listener);
  return () => entry.listeners.delete(listener);
}
