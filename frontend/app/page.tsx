"use client";

import { useEffect, useRef, useState } from "react";
import { QueryInput } from "@/components/chat/QueryInput";
import { MessageList } from "@/components/chat/MessageList";
import { Card } from "@/components/ui/Card";
import { createResearchRun, ApiError } from "@/lib/api";
import { streamResearch, type ResearchStreamHandle } from "@/lib/sse";
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

/** One finished query/answer exchange, archived into history once a new
 * query is submitted. Deliberately doesn't carry `steps` — the live
 * step-by-step streaming log is only ever shown for the current in-flight
 * query, not replayed for past ones (matches "query/answer exchanges"). */
interface Exchange {
  query: string;
  done: DoneEventData | null;
  error: string | null;
}

export default function HomePage() {
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

  // Auto-scroll the chat area to the latest activity — new message
  // submitted, a streaming step arrives, or the answer/error lands —
  // same behavior as ChatGPT/most chat apps, so the user never has to
  // scroll manually to see what just happened.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history, currentQuery, steps, done, error, isStreaming]);

  // Not wrapped in useCallback: archiving the *current* exchange into
  // history on every submit needs the latest currentQuery/done/error, and
  // a plain function closes over fresh state on every render — no stale
  // values, no need for refs just to read three related pieces of state
  // atomically.
  async function handleSubmit(query: string) {
    streamRef.current?.close();

    if (currentQuery !== null) {
      setHistory((prev) => [...prev, { query: currentQuery, done, error }]);
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
          <h1>Research Agent</h1>
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
