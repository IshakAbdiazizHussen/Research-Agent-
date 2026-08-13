import type { ProgressEventData } from "@/types/research";

const STATUS_LABELS: Record<string, string> = {
  pending: "Starting…",
  retrieving: "Retrieving sources",
  grading: "Grading sources",
  rewriting: "Refining search query",
  synthesizing: "Writing answer",
  completed: "Done",
  failed: "Failed",
};

function labelFor(status: string | null): string {
  if (!status) return "Working…";
  return STATUS_LABELS[status] ?? status;
}

interface StreamingStatusProps {
  /** Tool-role progress steps only — the final assistant answer is
   * rendered by MessageList, not duplicated here. */
  steps: ProgressEventData[];
  isStreaming: boolean;
}

export function StreamingStatus({ steps, isStreaming }: StreamingStatusProps) {
  if (steps.length === 0 && !isStreaming) return null;

  return (
    <ol className="streaming-status" aria-live="polite">
      {steps.map((step) => (
        <li key={step.sequence} className="streaming-status-step streaming-status-step-done">
          <span className="streaming-status-dot" aria-hidden="true" />
          <span className="streaming-status-label">{labelFor(step.status)}</span>
          <span className="streaming-status-detail">{step.content}</span>
        </li>
      ))}
      {isStreaming && (
        <li className="streaming-status-step streaming-status-step-active">
          <span className="streaming-status-dot streaming-status-dot-spinning" aria-hidden="true" />
          <span className="streaming-status-label">Working…</span>
        </li>
      )}
    </ol>
  );
}
