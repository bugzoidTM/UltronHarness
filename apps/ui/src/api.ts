export type Task = {
  id: string; title: string; objective: string; status: string; workspace: string;
  autonomy_mode: number; step_count: number; replan_count: number; tool_call_count: number;
  confidence?: number; cognitive_state?: string; created_at: string; updated_at: string; error?: string;
};
export type Goal = { id: string; title: string; description: string; priority: number; status: string; success_metric?: string };
export type Memory = { id: string; type: string; summary: string; content: string; importance: number; confidence: number; access_count: number; created_at: string; score?: number };
export type Event = { id?: string; type: string; task_id?: string; payload: Record<string, unknown>; created_at?: string };
export type SystemHealth = { status: string; database: boolean; llm: boolean; llm_generative: boolean; disk_free_gb: number; memory_available_gb: number; cpu_percent: number; memory_percent: number; model: { active: string; available?: boolean; generative?: boolean; detail?: string } };
export type ResearchRun = { id: string; benchmark: string; benchmark_version: string; mode: string; model_name: string; seed: number; score: number; passed: number; total: number; recovery_rate: number; average_steps: number; average_tool_calls: number; average_latency_ms: number; created_at: string };
export type DiagnosticRun = { id: string; experiment: string; hypothesis_id?: string; model_name: string; seed: number; result_json: string; artifact_dir: string; created_at: string };
export type ResearchDashboard = { runs: ResearchRun[]; experiments: any[]; model_comparison: any[]; cgfe: any[]; ablations: any[]; diagnostics: DiagnosticRun[]; context_metrics: { average_input_tokens?: number; calls?: number }; memory_utility: { memory_id: string; mean_delta: number; observations: number }[]; learn2: { id: string; result: { results?: { experience_count: number; fresh_score: number; experienced_score: number; cgfe: number }[] } }[]; transfer: { id: string; model_name: string; seed: number; fresh_score: number; experienced_score: number; transfer_gain: number; created_at: string }[]; memory_admission: { total: number; admitted?: number; mean_score?: number }; skills: { name: string; success_count: number; failure_count: number; last_used?: string; updated_at: string }[]; capabilities: { domain: string; task_type: string; success_rate: number; calibrated_score: number; uncertainty: number; sample_size: number; updated_at: string }[]; world_model: { observations: number; prediction_accuracy?: number; brier_score?: number }; hermes: { routing: { task_family: string; decision: string; decisions: number; mean_compatibility: number; mean_expected_utility: number; mean_observed_utility?: number }[]; family_utility: { task_family: string; experience_family: string; mean_delta: number; sample_count: number; ci95_low?: number; ci95_high?: number; state: string }[]; distillation: { id: string; family: string; principle: string; evidence_count: number; mean_utility: number }[]; skill_family: { skill_id: string; family: string; mean_delta: number; sample_count: number; state: string }[]; utility_calibration: { observations: number; mean_absolute_error?: number }; transfer100: { status?: string; completed_seeds?: number[]; statistics?: { transfer_gain?: { mean?: number; ci95_low?: number; ci95_high?: number } }; results?: unknown[] } }; forge?: { privacy?: { public_private_overlap?: number }[]; router_calibration?: any[]; router_target?: any[]; e2e?: { atc?: number; forge_4_passed?: boolean }[]; pair_utility?: { observations?: number; mean_delta?: number }; continuity?: { pending_continuations?: number }; execution_traces?: { events?: number; executions?: number } } };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }, ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || "Falha na comunicação com a API local.");
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<SystemHealth>("/system/health"),
  metrics: () => request<Record<string, unknown>>("/system/metrics"),
  tasks: () => request<Task[]>("/tasks"),
  task: (id: string) => request<Task & { plans: any[]; events: Event[]; tool_executions: any[]; approvals: any[] }>(`/tasks/${id}`),
  createTask: (body: { title: string; objective: string; goal_id?: string; workspace: string; autonomy_mode: number }) => request<Task>("/tasks", { method: "POST", body: JSON.stringify(body) }),
  runTask: (id: string) => request<Task>(`/tasks/${id}/run`, { method: "POST" }),
  pauseTask: (id: string) => request<{ status: string }>(`/tasks/${id}/pause`, { method: "POST" }),
  cancelTask: (id: string) => request<{ status: string }>(`/tasks/${id}/cancel`, { method: "POST" }),
  stop: () => request<{ message: string }>("/system/stop", { method: "POST" }),
  goals: () => request<Goal[]>("/goals"),
  createGoal: (body: { title: string; description: string; priority: number; success_metric?: string }) => request<Goal>("/goals", { method: "POST", body: JSON.stringify(body) }),
  memories: () => request<Memory[]>("/memories"),
  searchMemories: (query: string) => request<Memory[]>("/memories/search", { method: "POST", body: JSON.stringify({ query }) }),
  models: () => request<any[]>("/models"),
  tools: () => request<any[]>("/tools"),
  approvals: () => request<any[]>("/approvals"),
  decideApproval: (id: string, approved: boolean, note = "") => request<any>(`/approvals/${id}`, { method: "POST", body: JSON.stringify({ approved, note }) }),
  experiments: () => request<any[]>("/experiments"),
  benchmarks: () => request<any[]>("/benchmarks"),
  researchDashboard: () => request<ResearchDashboard>("/research/dashboard"),
  chat: (message: string, task_id?: string) => request<{ content: string; model: string; local: boolean; latency_ms: number }>("/chat", { method: "POST", body: JSON.stringify({ message, task_id }) })
};

export function connectEvents(onEvent: (event: Event) => void): () => void {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/events`);
  socket.onmessage = (message) => { try { onEvent(JSON.parse(message.data)); } catch { /* evento malformado é ignorado */ } };
  return () => socket.close();
}
