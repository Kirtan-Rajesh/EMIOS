import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "emios-theme";

interface ThemeContextValue {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readInitialTheme(): Theme {
  // Mirrors the inline bootstrap script in index.html (which already set
  // the "dark" class on <html> before this ever runs, to avoid a flash) -
  // this just brings React's own state in sync with what's already on the
  // page rather than re-deciding independently.
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/** Owns the light/dark theme toggle (AppShell's account menu - see
 * ThemeToggle) by adding/removing the "dark" class Tailwind's `dark:`
 * variant matches against (index.css's `@custom-variant dark`), and
 * persisting the choice to localStorage under the same "emios-theme" key
 * the pre-paint bootstrap script in index.html reads. Defaults to light
 * (the enterprise theme) for anyone who hasn't chosen yet - the original
 * "Blackout" dark theme is still there, opt-in via the toggle. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => setThemeState(next), []);
  const toggleTheme = useCallback(() => setThemeState((prev) => (prev === "dark" ? "light" : "dark")), []);

  return <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}
