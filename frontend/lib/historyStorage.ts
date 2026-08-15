/**
 * localStorage-backed persistence for the chat history list — a
 * refresh-survives-it convenience, client-side and this-browser-only by
 * explicit design (docs/architecture.md decision log): no backend/
 * database involvement, no cross-device sync. Only completed exchanges
 * are ever persisted here — the current in-flight query/streaming state
 * (app/page.tsx's currentQuery/steps/isStreaming) is deliberately never
 * written, so a refresh mid-query loses that query rather than resuming
 * it from a stale, broken half-state.
 */

import type { DoneEventData } from "@/types/research";

/** One finished query/answer exchange — the shape app/page.tsx has always
 * used internally; this module owns it now since it's the single source
 * of truth for what gets persisted. */
export interface Exchange {
  query: string;
  done: DoneEventData | null;
  error: string | null;
}

const STORAGE_KEY = "research-agent:history";

// Keeps localStorage usage bounded instead of growing forever. 50 is
// generous for "recent chat history in this browser" — most use of a
// single-device local tool like this won't scroll back further than that
// — while staying nowhere near localStorage's practical ~5MB/origin
// limit even for long answers with several sources each. Older entries
// drop off the front silently, not an error condition.
const MAX_STORED_EXCHANGES = 50;

function isExchangeShaped(value: unknown): value is Exchange {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.query === "string" &&
    (candidate.done === null || typeof candidate.done === "object") &&
    (candidate.error === null || typeof candidate.error === "string")
  );
}

/** Never throws. `window`/`localStorage` don't exist during Next.js's
 * server-side render pass (guarded explicitly, not just relying on the
 * try/catch, so the intent reads clearly); storage can also be
 * unavailable at runtime (private browsing, disabled) or hold corrupted
 * / stale-shape data from an earlier version of this app. Any of that
 * degrades to "no persisted history" — never a crash, never surfaced to
 * the user. */
export function loadHistory(): Exchange[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isExchangeShaped);
  } catch {
    return [];
  }
}

/** Same never-throws contract as loadHistory() — quota exceeded, private
 * browsing, storage disabled, etc. all degrade to "this session's
 * history just isn't persisted," not an error the user sees. */
export function saveHistory(history: Exchange[]): void {
  if (typeof window === "undefined") return;
  try {
    const capped = history.slice(-MAX_STORED_EXCHANGES);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(capped));
  } catch {
    // Non-fatal by design — see the docstring above.
  }
}

export function clearHistory(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Non-fatal by design — see the docstring above.
  }
}
