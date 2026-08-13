/**
 * Mirrors backend/app/api/routes/research.py's request/response and SSE
 * event shapes exactly. Kept in sync manually (docs/development_plan.md
 * Guidelines) — no shared-schema generation step exists yet. If the
 * backend's Pydantic models or SSE payloads change, update this file too.
 */

// backend/app/db/prisma/schema.prisma — MessageRole enum.
export type MessageRole = "user" | "assistant" | "system" | "tool";

// backend/app/db/prisma/schema.prisma — RunStatus enum.
export type RunStatus =
  | "pending"
  | "retrieving"
  | "grading"
  | "rewriting"
  | "synthesizing"
  | "completed"
  | "failed";

// backend/app/agent/state.py — Source (also ResearchRun.sources' shape).
export interface Source {
  url: string;
  title: string;
  snippet: string;
}

// backend/app/memory/base.py — MemoryResult.
export interface MemoryResult {
  text: string;
  metadata: Record<string, unknown>;
  score: number;
}

// POST /research request body.
export interface CreateResearchRunRequest {
  query: string;
}

// POST /research response body.
export interface CreateResearchRunResponse {
  id: string;
  related_past_research: MemoryResult[];
}

// GET /research/{id}/stream — `event: progress` payload.
export interface ProgressEventData {
  sequence: number;
  role: MessageRole;
  status: RunStatus | null;
  content: string;
}

// GET /research/{id}/stream — `event: done` payload. `note` is only
// present on the server-side stream-timeout path (research.py's
// _STREAM_MAX_WAIT_SECONDS), not a normal completion/failure.
export interface DoneEventData {
  status: Extract<RunStatus, "completed" | "failed">;
  answer: string | null;
  sources: Source[] | null;
  note?: string;
}

export type ResearchStreamEvent =
  | { type: "progress"; data: ProgressEventData }
  | { type: "done"; data: DoneEventData };
