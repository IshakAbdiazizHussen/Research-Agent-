/**
 * Fetch wrapper for backend endpoints (Feature 6: Frontend Research UI).
 * Every backend call goes through this file or lib/sse.ts — no inline
 * fetch()/EventSource calls inside components (docs/development_plan.md
 * Guidelines).
 *
 * Security (docs/development_plan.md): never embed or expose backend
 * secrets/API keys here. All env vars below are deliberately
 * NEXT_PUBLIC_* — a base URL, a dev-only placeholder email, and the
 * shared-secret gate value are not secrets in the traditional
 * confidentiality sense: NEXT_PUBLIC_* vars are always baked into the
 * public JS bundle, visible to any visitor. See NEXT_PUBLIC_APP_SHARED_SECRET
 * below for what that value actually protects against (and doesn't). No
 * API key belongs in this file, ever.
 */

import type { CreateResearchRunResponse } from "@/types/research";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Dev-only stand-in matching backend/app/core/deps.py's X-Dev-User-Email
// header. Never a substitute for real auth — see that file's own warning.
const DEV_USER_EMAIL = process.env.NEXT_PUBLIC_DEV_USER_EMAIL;

// Tier 1 production auth gate (post-launch audit finding — see
// docs/architecture.md decision log "Production auth: shared-secret gate +
// fixed identity"). Matched against backend/app/core/deps.py's
// settings.app_shared_secret via the X-App-Secret header. This does NOT
// keep the value confidential — it ships in the public bundle like every
// NEXT_PUBLIC_* var — it only proves a request came from someone who
// loaded this frontend, blocking unauthenticated internet noise hitting
// the bare API directly. It is unset (and harmless to omit) in local dev,
// since the backend only checks it when settings.is_production is true.
const APP_SHARED_SECRET = process.env.NEXT_PUBLIC_APP_SHARED_SECRET;

/** Shared auth header(s) for every backend call — one place, not re-typed
 * per call site (same convention the backend uses for TTLs/config). */
export function authHeaders(): HeadersInit {
  return {
    ...(DEV_USER_EMAIL ? { "X-Dev-User-Email": DEV_USER_EMAIL } : {}),
    ...(APP_SHARED_SECRET ? { "X-App-Secret": APP_SHARED_SECRET } : {}),
  };
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
        ...authHeaders(),
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
