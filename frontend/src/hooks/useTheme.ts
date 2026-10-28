import { useCallback, useEffect, useState } from "react";
import { safeStorage } from "../lib/storage";

type Theme = "light" | "dark";

const systemTheme = (): Theme => (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => (safeStorage.get("theme") as Theme | null) ?? systemTheme());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      safeStorage.set("theme", next);
      return next;
    });
  }, []);

  return { theme, toggle };
}
