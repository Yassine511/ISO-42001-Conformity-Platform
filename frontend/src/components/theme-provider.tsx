import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "int102-theme";

interface ThemeContextValue {
  theme: Theme;
  resolvedTheme: "light" | "dark";
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "system",
  resolvedTheme: "light",
  setTheme: () => {},
});

function systemTheme(): "light" | "dark" {
  // jsdom has no matchMedia — guard so tests render without a mock
  if (typeof window.matchMedia !== "function") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    /* storage unavailable */
  }
  return "system";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readStoredTheme);
  // The OS preference is STATE, not a value read during render. It used to be
  // recomputed by calling systemTheme() inline while the matchMedia listener
  // toggled the `dark` class imperatively — so an OS theme change repainted
  // the page but never re-rendered, and `resolvedTheme` handed consumers the
  // value from before the change. ThemeToggle reads it: the icon stayed on
  // the old theme and its first click computed `next` from the stale value,
  // i.e. set the theme the page was already showing and appeared to do
  // nothing.
  const [systemIsDark, setSystemIsDark] = useState(() => systemTheme() === "dark");
  const resolvedTheme: "light" | "dark" =
    theme === "system" ? (systemIsDark ? "dark" : "light") : theme;

  // Single writer of the `dark` class, driven by state alone.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
  }, [resolvedTheme]);

  // Tracks the OS unconditionally — not only while theme === "system". The
  // old effect unsubscribed on any explicit choice, so system -> dark ->
  // system came back with whatever `systemIsDark` held before.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => setSystemIsDark(media.matches);
    apply(); // resync: the preference may have changed before we subscribed
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* storage unavailable */
    }
  }, []);

  // Memoized: without it every consumer of useTheme() re-rendered whenever the
  // provider did, for an identical value.
  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme }),
    [theme, resolvedTheme, setTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
