/**
 * Every request goes through the Gateway — never straight to auth-service or
 * jobs-service, which aren't meant to be reachable from a browser at all
 * (docs/ARCHITECTURE.md).
 *
 * `credentials: "include"` is the single line that makes cookie auth work: without it
 * the browser won't send the httpOnly access_token/refresh_token cookies cross-origin
 * (frontend on :3000, gateway on :8000).
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
    const detail =
      typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    throw new ApiError(res.status, detail);
  }

  return res.status === 204 ? (undefined as T) : res.json();
}

export interface User {
  id: string;
  email: string;
  role: string;
}

export interface Profile {
  user_id: string;
  full_name: string | null;
  headline: string | null;
  skills: string | null;
  target_roles: string | null;
  countries: string;
  preferred_locations: string | null;
  remote_only: boolean;
  min_salary: number | null;
  seniority: string | null;
  resume_text: string | null;
}

export interface Job {
  posting_id: string;
  title: string;
  company_name: string | null;
  location: string | null;
  region: string | null;
  seniority: string | null;
  remote: boolean;
  salary: number | null;
  posted_month: number | null;
  required_skills?: string[];
}

export interface ToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  result_preview: string;
}

export interface AgentAnswer {
  agent: string;
  routing_reason?: string;
  answer: string;
  tool_calls: ToolCall[];
  iterations: number;
  stopped_early: boolean;
}

export interface Application {
  id: string;
  company: string;
  role: string | null;
  posting_id: string | null;
  status: string;
  resume_version: string | null;
  source: string;
  applied_at: string;
  updated_at: string;
}

export interface FunnelResponse {
  total_applications: number;
  rejected: number;
  awaiting_response: number;
  stages: { stage: string; count: number; percent_of_applied: number }[];
}

export interface ResumePerformance {
  resume_version: string;
  applications: number;
  positive_responses: number;
  response_rate_percent: number;
  sample_warning: string | null;
}

export interface GmailStatus {
  configured: boolean;
  connected: boolean;
  google_email?: string | null;
  last_synced_at?: string | null;
  message?: string;
}

export const api = {
  // ---- auth ----
  signup: (email: string, password: string) =>
    request<User>("/auth/signup", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),

  // ---- profile ----
  getProfile: () => request<Profile>("/profile"),
  updateProfile: (patch: Partial<Profile>) =>
    request<Profile>("/profile", { method: "PATCH", body: JSON.stringify(patch) }),

  // ---- jobs ----
  searchJobs: (params: Record<string, string | number | boolean | undefined>) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== false) query.set(k, String(v));
    });
    return request<{ total: number; limit: number; offset: number; jobs: Job[] }>(
      `/jobs/search?${query}`
    );
  },
  getJob: (postingId: string) => request<Job>(`/jobs/${postingId}`),

  // ---- analytics ----
  analytics: <T>(metric: string) => request<T>(`/analytics/${metric}`),

  // ---- applications & Gmail ----
  listApplications: () => request<Application[]>("/applications"),
  funnel: () => request<FunnelResponse>("/applications/funnel"),
  resumePerformance: () => request<ResumePerformance[]>("/applications/resume-performance"),
  syncInbox: () => request<{ queued: boolean; task_id: string }>("/applications/sync-inbox", { method: "POST" }),
  gmailStatus: () => request<GmailStatus>("/auth/google/status"),
  gmailConnect: () => request<{ authorization_url: string }>("/auth/google/connect"),

  // ---- agents ----
  listAgents: () =>
    request<Record<string, { description: string; tools: string[] }>>("/agents"),
  ask: (message: string, agent?: string) =>
    request<AgentAnswer>("/agents/ask", {
      method: "POST",
      body: JSON.stringify({ message, agent: agent || null }),
    }),
};
