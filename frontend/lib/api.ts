const BASE = "/api";

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
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
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
