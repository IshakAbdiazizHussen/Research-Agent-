"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";

/** Up-arrow glyph (lucide's "arrow-up", hand-copied — same convention as
 * ThemeToggle.tsx's Sun/Moon icons, no icon library installed for one
 * glyph). Replaces the submit button's "Research"/"Researching…" text
 * label per a reference image; aria-label below carries the equivalent
 * text for accessibility since there's no visible label anymore. */
function ArrowUpIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m5 12 7-7 7 7" />
      <path d="M12 19V5" />
    </svg>
  );
}

interface QueryInputProps {
  onSubmit: (query: string) => void;
  disabled: boolean;
}

export function QueryInput({ onSubmit, disabled }: QueryInputProps) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue("");
  }

  return (
    <form className="query-input" onSubmit={handleSubmit}>
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Ask a research question"
        disabled={disabled}
        aria-label="Research question"
      />
      <Button
        type="submit"
        disabled={disabled || value.trim().length === 0}
        aria-label={disabled ? "Researching…" : "Submit research question"}
        title={disabled ? "Researching…" : "Submit research question"}
      >
        <ArrowUpIcon />
      </Button>
    </form>
  );
}
