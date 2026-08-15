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
  if (!status) return STATUS_LABELS.pending;
  return STATUS_LABELS[status] ?? status;
}

/** Small filled circle + white checkmark — the "this step is done" icon.
 * Inline SVG rather than an icon library dependency this project doesn't
 * otherwise have. */
function CheckIcon() {
  return (
    <svg
      className="streaming-status-icon"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="8" fill="var(--color-accent)" />
      <path
        d="M4.5 8.3L7 10.8L11.5 5.8"
        fill="none"
        stroke="white"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface StreamingStatusProps {
  /** Tool-role progress steps only — the final assistant answer is
   * rendered by MessageList, not duplicated here. Each entry is a status
   * *transition* as it happened (backend/app/api/routes/research.py: one
   * SSE event per node change), so the last entry is always the step
   * currently in progress and every entry before it has, by definition,
   * already been superseded — no separate "is this step done" flag
   * needed in the data itself, just "is this the last one." */
  steps: ProgressEventData[];
  isStreaming: boolean;
}

/** Compact, progressive step indicator: prior steps collapse to a
 * checkmarked label (no detail), only the current step shows its
 * description — not a growing list of every step's full detail. Parent
 * (MessageList) already only renders this while isStreaming is true, but
 * the guard stays here too so this component doesn't assume a caller's
 * gating and is safe to use standalone. */
export function StreamingStatus({ steps, isStreaming }: StreamingStatusProps) {
  if (!isStreaming) return null;

  const completedSteps = steps.slice(0, -1);
  const currentStep = steps.length > 0 ? steps[steps.length - 1] : null;

  return (
    <div className="streaming-status" aria-live="polite">
      {completedSteps.map((step) => (
        <div key={step.sequence} className="streaming-status-step streaming-status-step-done">
          <CheckIcon />
          <span className="streaming-status-label">{labelFor(step.status)}</span>
        </div>
      ))}

      <div className="streaming-status-step streaming-status-step-active">
        <span className="streaming-status-dot streaming-status-dot-spinning" aria-hidden="true" />
        <div className="streaming-status-step-text">
          <span className="streaming-status-label">{labelFor(currentStep?.status ?? null)}</span>
          {currentStep?.content && (
            <span className="streaming-status-detail">{currentStep.content}</span>
          )}
        </div>
      </div>
    </div>
  );
}
