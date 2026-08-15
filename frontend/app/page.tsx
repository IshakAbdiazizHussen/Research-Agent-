"use client";

import { useRef, useState } from "react";
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
  // History renders most-recent-first, right below the current exchange —
  // the input stays fixed at the top of the page, so keeping the newest
  // result closest to it means never having to scroll after submitting.
  const [history, setHistory] = useState<Exchange[]>([]);

  const [currentQuery, setCurrentQuery] = useState<string | null>(null);
  const [relatedPastResearch, setRelatedPastResearch] = useState<MemoryResult[]>([]);
  const [steps, setSteps] = useState<ProgressEventData[]>([]);
  const [done, setDone] = useState<DoneEventData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  const streamRef = useRef<ResearchStreamHandle | null>(null);

  // Not wrapped in useCallback: archiving the *current* exchange into
  // history on every submit needs the latest currentQuery/done/error, and
  // a plain function closes over fresh state on every render — no stale
  // values, no need for refs just to read three related pieces of state
  // atomically.
  async function handleSubmit(query: string) {
    streamRef.current?.close();

    if (currentQuery !== null) {
      setHistory((prev) => [{ query: currentQuery, done, error }, ...prev]);
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
    <main className="page">
      <h1>Research Agent</h1>
      <p className="page-subtitle">
        Ask a question — it&apos;s researched live across the web, with cited sources.
      </p>

      <QueryInput onSubmit={handleSubmit} disabled={isStreaming} />

      {currentQuery && (
        <>
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

      {history.map((exchange, index) => (
        <MessageList
          key={`${history.length - index}-${exchange.query}`}
          query={exchange.query}
          done={exchange.done}
          error={exchange.error}
        />
      ))}
    </main>
  );
}
