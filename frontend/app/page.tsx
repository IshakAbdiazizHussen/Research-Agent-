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

// Exact copy from the reference image — not the earlier from-description
// draft (development_plan.md Feature 8).
const STEPS = [
  {
    title: "Ask a question",
    description: "Type any research question in plain language.",
  },
  {
    title: "Agent searches the live web",
    description: "It retrieves current sources in real time, not from a fixed training set.",
  },
  {
    title: "Sources are graded",
    description: "Weak or irrelevant results trigger an automatic retry with a refined query.",
  },
  {
    title: "You get a grounded answer",
    description: "Delivered with numbered, clickable citations back to the source.",
  },
];

const CAPABILITIES = [
  {
    title: "Live web search",
    description: "Every answer is backed by a real-time search of the web, not frozen training data.",
  },
  {
    title: "Grounded, cited answers",
    description: "Every claim links to a real source you can click through and verify yourself.",
  },
  {
    title: "Related past research",
    description: "See relevant questions you've asked before, surfaced right alongside new results.",
  },
  {
    title: "Real-time streaming progress",
    description: "Watch retrieval, grading, and synthesis happen live — never a silent black box.",
  },
];

export default function LandingPage() {
  return (
    <div className="landing-page">
      <section className="landing-hero">
        {/* No wrapper div needed — .theme-toggle-btn is always
            position:fixed to the viewport itself now (globals.css),
            shared identically with the chat header's toggle. */}
        <ThemeToggle />

        <h1 className="landing-headline">
          Ask a question.
          <br />
          Get a cited answer from the live web.
        </h1>

        <p className="landing-subhead">
          No stale training data, no made-up sources — every answer is grounded in real, current
          pages you can click through and verify.
        </p>

        <Link href="/app" className="landing-cta">
          Try it now
        </Link>
      </section>

      <section className="landing-sections">
        <div className="landing-section-inner landing-steps-wide">
          <h2 className="landing-section-title">How it works</h2>
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

        <div className="landing-section-inner">
          <h2 className="landing-section-title">Key capabilities</h2>
          <div className="landing-capabilities">
            {CAPABILITIES.map((capability) => (
              <div className="landing-capability-card" key={capability.title}>
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
