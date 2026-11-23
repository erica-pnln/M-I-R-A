"use client";

import { useEffect } from "react";

const THEME_STORAGE_KEY = "mira-theme";

export default function ThemeProvider({ children }) {
  useEffect(() => {
    let theme = "dark";
    try {
      const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (savedTheme === "light" || savedTheme === "dark") theme = savedTheme;
    } catch (error) {
      console.error("Could not load MIRA theme preference:", error);
    }

    document.documentElement.dataset.miraTheme = theme;
    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) metaThemeColor.setAttribute("content", theme === "light" ? "#f4f7fb" : "#000000");
  }, []);

  return children;
}
