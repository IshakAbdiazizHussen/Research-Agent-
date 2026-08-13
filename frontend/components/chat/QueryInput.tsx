"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";

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
        placeholder="Ask a research question…"
        disabled={disabled}
        aria-label="Research question"
      />
      <Button type="submit" disabled={disabled || value.trim().length === 0}>
        {disabled ? "Researching…" : "Research"}
      </Button>
    </form>
  );
}
