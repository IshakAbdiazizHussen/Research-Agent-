/**
 * SSE consumption for GET /research/{id}/stream (Feature 6: Frontend
 * Research UI).
 *
 * IMPORTANT — this is deliberately NOT the browser's native EventSource,
 * even though docs/development_plan.md's Implementation step describes
 * this file as an "EventSource wrapper": native EventSource cannot send
 * custom request headers, full stop — it's a browser API limitation, not
 * a configuration option. The backend's ownership check on the stream
 * endpoint (backend/app/api/routes/research.py) authenticates via the
 * X-Dev-User-Email header in development and the X-App-Secret header in
 * production (backend/app/core/deps.py), so native EventSource is not
 * actually usable against this backend as it exists today without either
 * (a) adding a second, query-string-based auth path to the backend, or
 * (b) parsing the stream manually via fetch(), which supports headers
 * normally. (b) was chosen — it's a frontend-only change, keeps the
 * single existing auth mechanism, and needs no backend changes beyond
 * what Feature 6 already touches. Flagging this explicitly rather than
 * silently renaming away from what the doc says.
 *
 * Every backend call goes through this file or lib/api.ts — no inline
 * fetch()/EventSource calls inside components (docs/development_plan.md
 * Guidelines).
 */

import { authHeaders, researchStreamUrl } from "./api";
import type {
  DoneEventData,
  ProgressEventData,
  ResearchStreamEvent,
} from "@/types/research";

interface StreamHandlers {
  onEvent: (event: ResearchStreamEvent) => void;
  /** Called only after reconnect attempts are exhausted — a transient
   * network blip is retried silently first (reconnect handling, per
   * docs/development_plan.md's Implementation step for this file). */
  onError: (error: Error) => void;
}

export interface ResearchStreamHandle {
  close: () => void;
}

const MAX_RECONNECT_ATTEMPTS = 3;
const RECONNECT_BASE_DELAY_MS = 500;

export function streamResearch(
  runId: string,
  handlers: StreamHandlers
): ResearchStreamHandle {
  const controller = new AbortController();
  let closed = false;

  void run();

  async function run(): Promise<void> {
    let attempt = 0;
    while (!closed) {
      try {
        await consume(runId, controller.signal, handlers.onEvent);
        return; // stream ended normally (a "done" event, or server closed it)
      } catch {
        if (closed || controller.signal.aborted) return;

        attempt += 1;
        // Fixed message only — never log the raw caught error here. This
        // path runs in the production build too, and the underlying error
        // could in principle carry backend/network detail (docs/
        // development_plan.md Security: no internal detail surfaced,
        // console output included, not just the rendered UI).
        console.warn(
          `research stream attempt ${attempt}/${MAX_RECONNECT_ATTEMPTS} failed; retrying.`
        );
        if (attempt > MAX_RECONNECT_ATTEMPTS) {
          handlers.onError(new Error("Lost connection to the research stream. Please try again."));
          return;
        }
        await sleep(RECONNECT_BASE_DELAY_MS * attempt);
      }
    }
  }

  return {
    close: () => {
      closed = true;
      controller.abort();
    },
  };
}

async function consume(
  runId: string,
  signal: AbortSignal,
  onEvent: (event: ResearchStreamEvent) => void
): Promise<void> {
  const response = await fetch(researchStreamUrl(runId), {
    headers: authHeaders(),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`Stream request failed with status ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;

    // The server sends CRLF line endings ("\r\n") — normalize to LF before
    // frame-splitting, since "\r\n\r\n" contains no adjacent "\n\n" pair
    // and would otherwise never match (every frame would silently sit in
    // `buffer`, unparsed, until the stream closed and was discarded).
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    let frameEnd = buffer.indexOf("\n\n");
    while (frameEnd !== -1) {
      const frame = buffer.slice(0, frameEnd);
      buffer = buffer.slice(frameEnd + 2);

      const event = parseFrame(frame);
      if (event) {
        onEvent(event);
        if (event.type === "done") return;
      }

      frameEnd = buffer.indexOf("\n\n");
    }
  }
}

/** Parses one SSE frame ("event: X\ndata: Y"). Returns null for anything
 * that isn't a recognized progress/done event — including keep-alive
 * comment frames (lines starting with ":"), which sse_starlette sends
 * periodically and which must be silently ignored, not treated as
 * malformed. */
function parseFrame(frame: string): ResearchStreamEvent | null {
  let eventType = "";
  let data = "";

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      eventType = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      data += line.slice("data:".length).trim();
    }
  }

  if (!data) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }

  if (eventType === "progress") {
    return { type: "progress", data: parsed as ProgressEventData };
  }
  if (eventType === "done") {
    return { type: "done", data: parsed as DoneEventData };
  }
  return null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
