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

// The four step cards under "How it works" — exact copy from a later
// reference image, matching the graph's actual node names (agent/graph.py)
// rather than the earlier removed section's more descriptive phrasing.
const STEPS = [
  {
    title: "Retrieve",
    description: "Searches the live web for pages that could answer the question.",
  },
  {
    title: "Grade",
    description: "Scores each source for relevance and drops the ones that miss.",
  },
  {
    title: "Retry",
    description: "If too little survives grading, it rewrites the query and searches again.",
  },
  {
    title: "Synthesize",
    description: "Writes the answer from the graded sources, with a citation per claim.",
  },
];

// "Capabilities" section under "How it works" — exact copy from a later
// reference image.
const CAPABILITIES = [
  {
    title: "Live web search",
    description: "Queries run at ask time, so answers reflect what is published today, not a training cutoff.",
  },
  {
    title: "Grounded, cited answers",
    description: "Every claim carries a numbered citation you can open and read yourself.",
  },
  {
    title: "Related past research",
    description:
      "When a new question resembles one you have already asked, the earlier thread surfaces alongside it.",
  },
  {
    title: "Streaming progress",
    description: "Each retrieval, grade and retry appears as it runs. Nothing happens behind a spinner.",
  },
];

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

      <section className="landing-how">
        <div className="landing-how-inner">
          <p className="landing-how-eyebrow">How it works</p>
          <h2 className="landing-how-heading">
            Four steps run on every question. You watch them happen.
          </h2>

          <div className="landing-steps">
            {STEPS.map((step, index) => (
              <div className="landing-step" key={step.title}>
                <div className="landing-step-number">{index + 1}</div>
                <h3 className="landing-step-title">{step.title}</h3>
                <p className="landing-step-desc">{step.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="landing-capabilities">
        <div className="landing-capabilities-inner">
          {/* Same eyebrow style as "How it works" above — reused directly
              rather than duplicated, since the two are visually identical. */}
          <p className="landing-how-eyebrow">Capabilities</p>

          <div className="landing-capabilities-grid">
            {CAPABILITIES.map((capability) => (
              <div className="landing-capability" key={capability.title}>
                <h3 className="landing-capability-title">{capability.title}</h3>
                <p className="landing-capability-desc">{capability.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
