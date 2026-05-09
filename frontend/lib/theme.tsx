"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type ThemeMode = "light" | "dark" | "adaptive";
type ResolvedTheme = "light" | "dark";

type ThemeContextValue = {
  mode: ThemeMode;
  resolvedTheme: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
};

const STORAGE_KEY = "caregiver-companion-theme";
const ThemeContext = createContext<ThemeContextValue | null>(null);

function isThemeMode(value: string | null): value is ThemeMode {
  return value === "light" || value === "dark" || value === "adaptive";
}

function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined") {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>("adaptive");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("light");

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (isThemeMode(stored)) {
      setModeState(stored);
    }
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");

    function applyTheme() {
      setResolvedTheme(mode === "adaptive" ? systemTheme() : mode);
    }

    applyTheme();
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [mode]);

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
    document.documentElement.dataset.themeMode = mode;
    document.documentElement.style.colorScheme = resolvedTheme;
    document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
  }, [mode, resolvedTheme]);

  function setMode(nextMode: ThemeMode) {
    setModeState(nextMode);
    window.localStorage.setItem(STORAGE_KEY, nextMode);
  }

  const value = useMemo(() => ({ mode, resolvedTheme, setMode }), [mode, resolvedTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside ThemeProvider");
  }
  return context;
}
