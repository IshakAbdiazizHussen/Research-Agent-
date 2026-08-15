"use client";

import { useEffect, useState } from "react";
import { applyTheme, getActiveTheme, setStoredTheme, type Theme } from "@/lib/theme";

/** Sun icon (lucide's "sun" glyph, hand-copied — no icon library is
 * installed in this project yet, and adding one for two static glyphs
 * isn't worth the new dependency). Shown when the app is in dark mode:
 * clicking switches TO light. currentColor so it follows the button's
 * --color-text in both themes with no separate light/dark icon color to
 * maintain. */
function SunIcon() {
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
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}

/** Moon icon (lucide's "moon" glyph, same reasoning as SunIcon above).
 * Shown when the app is in light mode: clicking switches TO dark. */
function MoonIcon() {
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
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
    </svg>
  );
}

/** "Light mode" / "Dark mode" toggle — reachable from both the landing
 * page and the chat interface header (development_plan.md Feature 8),
 * always position:fixed to the viewport's top-right corner on both
 * routes (see .theme-toggle-btn in globals.css).
 *
 * Icon-only: the glyph shown is the mode clicking it switches TO (sun in
 * dark mode → switches to light; moon in light mode → switches to dark)
 * — same "names the destination, not the current state" convention the
 * original text label used, just expressed as an icon instead of words.
 * aria-label/title carry the equivalent text for accessibility and a
 * hover tooltip now that there's no visible label.
 *
 * Starts rendering as "light" and corrects itself via useEffect on
 * mount, rather than reading the real active theme synchronously up
 * front — deliberately, same reasoning as historyStorage's hydration
 * effect: the server can't know the client's stored choice or system
 * preference, so a lazy useState initializer here would risk a real
 * hydration mismatch. The actual page COLORS never flash wrong (the
 * inline script in app/layout.tsx already set [data-theme] before first
 * paint) — only this button's own icon could, for a single frame, on a
 * client that turns out to be in dark mode. Accepted as negligible: it
 * self-corrects before a user could plausibly notice. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    setTheme(getActiveTheme());
  }, []);

  function handleClick() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
    setStoredTheme(next);
  }

  const label = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";

  return (
    <button
      type="button"
      className="theme-toggle-btn"
      onClick={handleClick}
      aria-label={label}
      title={label}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
