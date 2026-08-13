/**
 * Fetch wrapper for backend endpoints (Feature 6: Frontend Research UI).
 * Every backend call goes through this file or lib/sse.ts — no inline
 * fetch()/EventSource calls inside components (docs/development_plan.md
 * Guidelines).
 *
 * Security (docs/development_plan.md): never embed or expose backend
 * secrets/API keys here. Both env vars below are deliberately
 * NEXT_PUBLIC_* — a base URL and a dev-only placeholder email are not
 * secrets. No API key belongs in this file, ever.
 */

import type { CreateResearchRunResponse } from "@/types/research";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Dev-only stand-in matching backend/app/core/deps.py's X-Dev-User-Email
// header. Never a substitute for real auth — see that file's own warning.
const DEV_USER_EMAIL = process.env.NEXT_PUBLIC_DEV_USER_EMAIL;

/** Shared auth header(s) for every backend call — one place, not re-typed
 * per call site (same convention the backend uses for TTLs/config). */
export function devAuthHeaders(): HeadersInit {
  return DEV_USER_EMAIL ? { "X-Dev-User-Email": DEV_USER_EMAIL } : {};
}

export class ApiError extends Error {}

/** POST /research — create a run and kick off graph execution. Throws
 * ApiError with a safe, generic message on failure; never surfaces raw
 * backend error text (docs/development_plan.md Security). */
export async function createResearchRun(
  query: string
): Promise<CreateResearchRunResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/research`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...devAuthHeaders(),
      },
      body: JSON.stringify({ query }),
    });
  } catch {
    throw new ApiError("Could not reach the research service. Please try again.");
  }

  if (!response.ok) {
    throw new ApiError("Could not start this research run. Please try again.");
  }

  return (await response.json()) as CreateResearchRunResponse;
}

/** GET /research/{id}/stream URL — lib/sse.ts is what actually consumes
 * it (fetch-based, not native EventSource; see that file for why). */
export function researchStreamUrl(runId: string): string {
  return `${API_BASE_URL}/research/${runId}/stream`;
}
