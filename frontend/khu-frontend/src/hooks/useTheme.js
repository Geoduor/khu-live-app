import { useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "khu_theme";

/**
 * useTheme — dark/light mode toggle, persisted per-device (localStorage),
 * same zero-friction pattern as useFavorites. Applies the choice via a
 * data-theme attribute on <html>, so every CSS variable defined under
 * :root[data-theme="light"] / :root[data-theme="dark"] cascades
 * automatically — no need to touch individual components.
 *
 * Defaults to the device's OS-level preference (prefers-color-scheme)
 * on first visit, then respects whatever the user explicitly picks
 * afterward.
 */
export function useTheme() {
  const [theme, setTheme] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "light" || stored === "dark") return stored;
    } catch {
      // localStorage unavailable — fall through to OS preference
    }
    const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
    return prefersLight ? "light" : "dark";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // fail silently, same as useFavorites — theme just won't persist
    }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return { theme, toggleTheme, isDark: theme === "dark" };
}
