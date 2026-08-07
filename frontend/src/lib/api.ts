/**
 * Every request goes through the Gateway (never straight to auth-service/agent-service —
 * those aren't meant to be reachable from the browser, see docs/ARCHITECTURE.md).
 *
 * `credentials: "include"` is the one line that makes cookie-based auth work at all:
 * without it, the browser won't send the httpOnly access_token/refresh_token cookies
 * cross-origin (frontend on :3000, gateway on :8000).
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options.headers },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? "Request failed");
  }

  // 204 / empty bodies (e.g. logout) — nothing to parse
  return res.status === 204 ? (undefined as T) : res.json();
}

export interface User {
  id: string;
  email: string;
  role: string;
}

export const api = {
  signup: (email: string, password: string) =>
    request<User>("/auth/signup", { method: "POST", body: JSON.stringify({ email, password }) }),

  login: (email: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),

  logout: () => request<void>("/auth/logout", { method: "POST" }),

  me: () => request<User>("/auth/me"),

  extractSkills: (jobDescription: string) =>
    request<{ result: unknown }>("/agents/orchestrator", {
      method: "POST",
      body: JSON.stringify({ intent: "extract_skills", payload: { job_description: jobDescription } }),
    }),
};
