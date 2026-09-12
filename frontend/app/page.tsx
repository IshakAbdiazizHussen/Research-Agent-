import type { Metadata } from "next";
import Link from "next/link";
import { ThemeToggle } from "@/components/theme/ThemeToggle";

// Overrides the root layout's default title for this route only (Next.js
// App Router metadata merging) — development_plan.md Feature 8.
export const metadata: Metadata = {
  title: "Research Agent — Ask, Search, Verify",
  description:
    "Ask a question and get a cited answer from the live web — no stale training data, no made-up sources.",
};

// Redesigned against an exact reference image (single hero, no "How it
// works"/"Key capabilities" sections below it) — replaces the earlier
// gradient hero + sections layout entirely, per instruction to match the
// reference exactly rather than add to what existed before.
export default function LandingPage() {
  return (
    <div className="landing-page">
      <section className="landing-hero">
        {/* .theme-toggle-btn is always position:fixed to the viewport
            itself (globals.css), shared identically with the chat
            header's toggle — unchanged by this redesign. */}
        <ThemeToggle />

        <span className="landing-badge">
          <span className="landing-badge-dot" aria-hidden="true" />
          Research Agent
        </span>

        <h1 className="landing-headline">
          Answers built from the live web,
          <br />
          with the sources attached.
        </h1>

        <p className="landing-subhead">
          Ask a question in plain language. The agent searches, grades what it finds, retries
          when the results are weak, and cites every claim.
        </p>

        <Link href="/app" className="landing-cta">
          Try it now
        </Link>
      </section>
    </div>
  );
}
