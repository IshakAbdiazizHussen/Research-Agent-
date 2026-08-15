/**
 * Theme (light/dark) persistence + application (development_plan.md
 * Feature 8: Landing Page & Theme System). Same client-side, this-
 * browser-only pattern as lib/historyStorage.ts — no backend involved.
 *
 * The actual pre-paint application (avoiding a flash of the wrong theme
 * on load) happens via a small inline script in app/layout.tsx, which
 * necessarily duplicates this module's storage key and precedence logic
 * in plain JS — it has to run before any bundled JS (including this
 * module) is even parsed, so it can't import from here. That
 * duplication is intentional, not drift risk: if the precedence rule
 * here ever changes, the inline script must be updated to match, and
 * there's no way around that given the constraint it runs under.
 */

export type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "research-agent:theme";

/** The user's explicit choice, if they've ever made one — never throws;
 * unavailable/corrupted storage or no choice yet both read as null. */
export function getStoredTheme(): Theme | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    return raw === "light" || raw === "dark" ? raw : null;
  } catch {
    return null;
  }
}

export function setStoredTheme(theme: Theme): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Non-fatal — same contract as lib/historyStorage.ts.
  }
}

export function getSystemTheme(): Theme {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** The theme actually in effect right now: explicit stored choice first,
 * else system preference — the same precedence the inline FOUC-
 * prevention script and the CSS cascade (globals.css: bare :root, then
 * the prefers-color-scheme media query, then [data-theme]) both use. */
export function getActiveTheme(): Theme {
  return getStoredTheme() ?? getSystemTheme();
}

export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
}
