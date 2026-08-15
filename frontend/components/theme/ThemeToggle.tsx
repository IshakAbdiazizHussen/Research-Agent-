"use client";

import { useEffect, useState } from "react";
import { applyTheme, getActiveTheme, setStoredTheme, type Theme } from "@/lib/theme";

/** "Dark mode" / "Light mode" toggle — reachable from both the landing
 * page hero and the chat interface header (development_plan.md Feature
 * 8). Label names the theme clicking it switches TO, not the current one
 * (matches the reference design: a light page shows a button labeled
 * "Dark mode").
 *
 * Starts rendering as "light" and corrects itself via useEffect on
 * mount, rather than reading the real active theme synchronously up
 * front — deliberately, same reasoning as historyStorage's hydration
 * effect: the server can't know the client's stored choice or system
 * preference, so a lazy useState initializer here would risk a real
 * hydration mismatch. The actual page COLORS never flash wrong (the
 * inline script in app/layout.tsx already set [data-theme] before first
 * paint) — only this button's own label text could, for a single frame,
 * on a client that turns out to be in dark mode. Accepted as
 * negligible: it's label text, not a visible theme flash, and self-
 * corrects before a user could plausibly notice. */
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

  return (
    <button type="button" className="theme-toggle-btn" onClick={handleClick}>
      {theme === "dark" ? "Light mode" : "Dark mode"}
    </button>
  );
}
