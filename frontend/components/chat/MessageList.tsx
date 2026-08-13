import { Card } from "@/components/ui/Card";
import type { DoneEventData } from "@/types/research";

interface MessageListProps {
  query: string;
  done: DoneEventData | null;
  /** Already a safe, generic message by the time it reaches here — see
   * lib/sse.ts / lib/api.ts, which never forward raw backend error text
   * (docs/development_plan.md Security). */
  error: string | null;
}

const GENERIC_FAILURE_MESSAGE =
  "This research run could not be completed. Please try again.";

export function MessageList({ query, done, error }: MessageListProps) {
  return (
    <div className="message-list">
      <Card className="message message-user">
        <p className="message-role">You asked</p>
        <p>{query}</p>
      </Card>

      {error && (
        <Card className="message message-error" role="alert">
          <p className="message-role">Something went wrong</p>
          <p>{error}</p>
        </Card>
      )}

      {done && (
        <Card
          className={
            done.status === "completed" ? "message message-assistant" : "message message-error"
          }
          role={done.status === "failed" ? "alert" : undefined}
        >
          <p className="message-role">
            {done.status === "completed" ? "Answer" : "Something went wrong"}
          </p>
          <p>{done.answer ?? GENERIC_FAILURE_MESSAGE}</p>

          {done.sources && done.sources.length > 0 && (
            <ol className="sources-list">
              {done.sources.map((source, index) => (
                <li key={`${source.url}-${index}`}>
                  <a href={source.url} target="_blank" rel="noreferrer noopener">
                    [{index + 1}] {source.title || source.url}
                  </a>
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}
    </div>
  );
}
