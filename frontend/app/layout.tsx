import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Research Agent",
  description: "Ask a research question and get a cited, sourced answer.",
};

// Sets [data-theme] on <html> before the browser paints anything, so
// there's no visible flash of the wrong theme on load (development_plan.md
// Feature 8). Plain, dependency-free JS deliberately, not a call into
// lib/theme.ts — this has to run synchronously in <head>, before any
// bundled module (including that one) is even parsed, so it can't import
// it; the storage key and light/dark precedence logic are duplicated here
// on purpose, see lib/theme.ts's own docstring for why that's accepted.
// Wrapped in try/catch so a genuinely broken localStorage (not just
// absent) can't block the page from rendering at all.
const THEME_INIT_SCRIPT = `(function(){try{var s=localStorage.getItem("research-agent:theme");var t=s==="light"||s==="dark"?s:(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");document.documentElement.setAttribute("data-theme",t);}catch(e){}})();`;

// suppressHydrationWarning below is scoped to the <html> element only
// (React does not propagate it to children) — required here, not
// optional polish: the inline script deliberately sets [data-theme] on
// this exact element before React hydrates, which is a genuine, expected
// difference from what the server rendered (the server has no way to
// know the client's stored theme or system preference). Without this,
// React logs a hydration-mismatch warning on every load — confirmed via
// a real Playwright console-error capture during QA, not assumed — even
// though the resulting DOM/behavior is correct either way. This is the
// documented fix for exactly this pattern (used by next-themes and
// equivalent solutions), not a blanket suppression: it does not hide
// mismatches anywhere else in the tree.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
