"use client";

import { useEffect, useRef, useState } from "react";
import { QueryInput } from "@/components/chat/QueryInput";
import { MessageList } from "@/components/chat/MessageList";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { createResearchRun, ApiError } from "@/lib/api";
import { streamResearch, type ResearchStreamHandle } from "@/lib/sse";
import { clearHistory, loadHistory, saveHistory, type Exchange } from "@/lib/historyStorage";
import type { DoneEventData, MemoryResult, ProgressEventData } from "@/types/research";

const GENERIC_START_ERROR = "Could not start this research run. Please try again.";

/** The original query text of a related past run — metadata is
 * Record<string, unknown> (backend/app/memory/base.py's MemoryResult), so
 * this is read defensively rather than assumed. Falls back to the stored
 * summary text if the query isn't there for some reason. */
function relatedRunLabel(item: MemoryResult): string {
  const query = item.metadata?.query;
  return typeof query === "string" && query.length > 0 ? query : item.text;
}

function RelatedPastResearch({ items }: { items: MemoryResult[] }) {
  // Most queries have no related past research, especially early in usage
  // — omit the section entirely rather than showing an empty/awkward
  // placeholder (Feature 6 QA follow-up).
  if (items.length === 0) return null;

  return (
    <Card className="related-research">
      <p className="message-role">Related past research</p>
      <ul>
        {items.map((item, index) => (
          <li key={index}>
            <span className="related-research-query">{relatedRunLabel(item)}</span>
            <span className="related-research-score">{Math.round(item.score * 100)}% match</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function ChatPage() {
  // Chronological order (oldest first) — the complement of a fixed-bottom
  // input: new exchanges append to the end, appearing directly above where
  // the user just typed, not pushing older ones further away. Appending
  // (not prepending) here means render order is already correct with no
  // reversal needed at render time.
  const [history, setHistory] = useState<Exchange[]>([]);

  const [currentQuery, setCurrentQuery] = useState<string | null>(null);
  const [relatedPastResearch, setRelatedPastResearch] = useState<MemoryResult[]>([]);
  const [steps, setSteps] = useState<ProgressEventData[]>([]);
  const [done, setDone] = useState<DoneEventData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  const streamRef = useRef<ResearchStreamHandle | null>(null);
  // Sentinel scrolled into view on every update below — simpler and more
  // robust than tracking scrollTop/scrollHeight by hand.
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // Hydrate persisted history from localStorage once, on mount, client-
  // side only. Can't read localStorage during Next.js's server-side
  // render pass (no `window` there — loadHistory() guards for that
  // itself); doing this inside useState()'s own initializer instead of
  // an effect would also cause a hydration mismatch (server always
  // renders starting from [], so the client's very first render must
  // match that before this runs) — a useEffect fires only after that
  // first render has already committed, avoiding the mismatch entirely,
  // at the cost of one effectively-instant extra render once real data
  // loads.
  useEffect(() => {
    setHistory(loadHistory());
  }, []);

  // Auto-scroll the chat area to the latest activity — new message
  // submitted, a streaming step arrives, or the answer/error lands —
  // same behavior as ChatGPT/most chat apps, so the user never has to
  // scroll manually to see what just happened.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history, currentQuery, steps, done, error, isStreaming]);

  function handleClearHistory() {
    setHistory([]);
    clearHistory();
  }

  // Persists the *current* exchange too, the moment it actually finishes
  // (guarded below: never while isStreaming, never before done/error has
  // resolved — a mid-query refresh must still lose it, per spec) —
  // without this, the single most-recently-completed exchange would be
  // lost on a refresh even though it's fully done, not in-flight, simply
  // because the *rendering* split only archives it into `history` state
  // once the *next* query is submitted (unchanged, see handleSubmit).
  // This only ever writes to storage, never to `history` state itself —
  // the current/history rendering split stays exactly as it was; this is
  // purely about what survives a reload versus what's currently "live."
  useEffect(() => {
    if (currentQuery === null || isStreaming) return;
    if (done === null && error === null) return;
    saveHistory([...history, { query: currentQuery, done, error }]);
  }, [history, currentQuery, done, error, isStreaming]);

  // Not wrapped in useCallback: archiving the *current* exchange into
  // history on every submit needs the latest currentQuery/done/error, and
  // a plain function closes over fresh state on every render — no stale
  // values, no need for refs just to read three related pieces of state
  // atomically.
  async function handleSubmit(query: string) {
    streamRef.current?.close();

    if (currentQuery !== null) {
      // Persisted explicitly here, alongside the state update, rather
      // than via a separate useEffect watching `history` — this (and
      // handleClearHistory above) are the *only* two places `history`
      // ever changes, so there's no risk of missing a change, and it
      // sidesteps a real timing hazard an effect-based approach would
      // have: on mount, the hydration effect above and a naive "save on
      // every history change" effect would both run in the same commit,
      // with the save effect still seeing history=[] from that same
      // render — silently overwriting real stored data with an empty
      // array before the hydrated value ever got a chance to render.
      const nextHistory = [...history, { query: currentQuery, done, error }];
      setHistory(nextHistory);
      saveHistory(nextHistory);
    }

    setCurrentQuery(query);
    setRelatedPastResearch([]);
    setSteps([]);
    setDone(null);
    setError(null);
    setIsStreaming(true);

    let runId: string;
    try {
      const created = await createResearchRun(query);
      runId = created.id;
      setRelatedPastResearch(created.related_past_research);
    } catch (err) {
      setIsStreaming(false);
      setError(err instanceof ApiError ? err.message : GENERIC_START_ERROR);
      return;
    }

    streamRef.current = streamResearch(runId, {
      onEvent: (event) => {
        if (event.type === "progress") {
          // The final assistant answer arrives as a progress event too
          // (it's a Message row like any other step) — MessageList
          // renders it from the "done" event instead, so only "tool"
          // role steps go into the streaming status list.
          if (event.data.role === "tool") {
            setSteps((prev) => [...prev, event.data]);
          }
        } else {
          setDone(event.data);
          setIsStreaming(false);
        }
      },
      onError: (err) => {
        setIsStreaming(false);
        setError(err.message);
      },
    });
  }

  return (
    <div className="chat-shell">
      <div className="chat-scroll">
        <main className="page">
          <div className="page-header">
            <h1>Research Agent</h1>
            <div className="page-header-actions">
              <ThemeToggle />
              {history.length > 0 && (
                <Button variant="secondary" className="btn-sm" onClick={handleClearHistory}>
                  Clear chat
                </Button>
              )}
            </div>
          </div>
          <p className="page-subtitle">
            {/* Two variants, CSS-switched by media query (not JS) — same
             * approach as the rest of this file's responsive behavior,
             * and avoids a hydration mismatch since both are always in
             * the DOM, only visibility changes. */}
            <span className="subtitle-long">
              Ask a question — I&apos;ll search the live web and give you a cited answer.
            </span>
            <span className="subtitle-short">
              Ask a question — get a cited, grounded answer.
            </span>
          </p>

          {history.length === 0 && !currentQuery && (
            <p className="empty-state">Ask a research question to get started.</p>
          )}

          {history.map((exchange, index) => (
            <MessageList
              key={`${index}-${exchange.query}`}
              query={exchange.query}
              done={exchange.done}
              error={exchange.error}
            />
          ))}

          {currentQuery && (
            <>
              {/* Inline, right above the exchange it relates to, rather
               * than pinned near the (now-bottom) input — it's about the
               * query just submitted, so it reads best sitting in the
               * scrolling chat flow next to that query, not anchored to
               * UI chrome that no longer sits near the top. */}
              <RelatedPastResearch items={relatedPastResearch} />
              <MessageList
                query={currentQuery}
                done={done}
                error={error}
                steps={steps}
                isStreaming={isStreaming}
              />
            </>
          )}

          <div ref={bottomRef} />
        </main>
      </div>

      <div className="chat-input-bar">
        <div className="chat-input-bar-inner">
          <QueryInput onSubmit={handleSubmit} disabled={isStreaming} />
        </div>
      </div>
    </div>
  );
}
