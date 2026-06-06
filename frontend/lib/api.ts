// Local dev: BASE = "/api" → next.config.ts rewrites to http://localhost:8000.
// Production (Vercel): set NEXT_PUBLIC_API_URL=https://<render-app>.onrender.com/api
// to call the Render backend directly. CORS middleware on the backend allows it.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

// ─── User-supplied API key override ─────────────────────────────────────────
// If the user has pasted a personal GitHub PAT on the Settings page, we read
// it from localStorage and send it as X-Github-Token. The backend's
// set_github_token_override() consumes it. Falls back to env GITHUB_TOKEN
// (configured on Render) when absent — i.e. no header sent ≠ broken request.
export const USER_TOKENS_KEY = "repomind:user-tokens:v1";

export function getStoredGithubToken(): string {
  if (typeof window === "undefined") return "";
  try {
    const raw = window.localStorage.getItem(USER_TOKENS_KEY);
    if (!raw) return "";
    const parsed = JSON.parse(raw) as { github_token?: string };
    return (parsed.github_token ?? "").trim();
  } catch {
    return "";
  }
}

export function setStoredGithubToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    if (token.trim()) {
      window.localStorage.setItem(
        USER_TOKENS_KEY,
        JSON.stringify({ github_token: token.trim() }),
      );
    } else {
      window.localStorage.removeItem(USER_TOKENS_KEY);
    }
  } catch {
    /* private mode / quota — silent */
  }
}

function authHeaders(): Record<string, string> {
  const t = getStoredGithubToken();
  return t ? { "X-Github-Token": t } : {};
}

export interface Collection {
  name: string;
  chunk_count: number;
}

export interface LogEntry {
  timestamp: string;
  session_id: string;
  step: number;
  event: string;
  data: Record<string, unknown>;
}

export interface Metrics {
  total_sessions?: number;
  avg_latency_s?: number;
  median_latency_s?: number;
  avg_steps?: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_cost_usd?: number;
}

export interface ContextMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AgentResult {
  session_id: string;
  answer: string;
  steps: number;
  stop_reason: string;
  total_latency_s: number;
  embed_ms: number | null;
  chroma_ms: number | null;
  compressed_history: ContextMessage[];
}

export async function fetchCollections(): Promise<Collection[]> {
  const res = await fetch(`${BASE}/collections`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.collections ?? [];
}

export async function ingestRepo(repo: string, mode: string): Promise<void> {
  const res = await fetch(`${BASE}/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ repo, mode }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Ingest failed (${res.status})`);
  }
}

export async function triggerQuery(
  query: string,
  collection_name: string,
  history: ContextMessage[] = []
): Promise<string> {
  const res = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ query, collection_name, history }),
  });
  if (!res.ok) throw new Error(`Query trigger failed (${res.status})`);
  const data = await res.json();
  return data.session_id as string;
}

export async function pollResult(
  sessionId: string
): Promise<AgentResult | null> {
  const res = await fetch(`${BASE}/result/${sessionId}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Poll failed (${res.status})`);
  return res.json();
}

export async function fetchLogs(limit = 50): Promise<LogEntry[]> {
  const res = await fetch(`${BASE}/logs?limit=${limit}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.logs ?? [];
}

export async function fetchSessionLogs(sessionId: string): Promise<LogEntry[]> {
  const res = await fetch(`${BASE}/logs/${sessionId}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.logs ?? [];
}

export async function fetchMetrics(): Promise<Metrics> {
  const res = await fetch(`${BASE}/metrics`);
  if (!res.ok) return {};
  return res.json();
}
