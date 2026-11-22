"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import { translate } from "@/lib/locale";
import { supabase } from "@/lib/supabase";

const LanguageContext = createContext(null);
const SUPPORTED_LANGUAGES = new Set(["en", "fil", "ceb"]);

export function LanguageProvider({ children }) {
  const [language, setLanguageState] = useState("en");
  const languageRef = useRef(language);
  languageRef.current = language;

  const setLanguage = useCallback((value) => {
    const nextLanguage = SUPPORTED_LANGUAGES.has(value) ? value : "en";
    setLanguageState(nextLanguage);
    if (typeof document !== "undefined") document.documentElement.lang = nextLanguage;
  }, []);

  useEffect(() => {
    document.title = translate(language, "MIRA — Go Beyond the Headline");
    const description = document.querySelector('meta[name="description"]');
    if (description) {
      description.setAttribute(
        "content",
        translate(language, "AI-powered news discovery and research for journalists."),
      );
    }
  }, [language]);

  useEffect(() => {
    let active = true;
    let revision = 0;

    async function loadLanguage(session) {
      const currentRevision = ++revision;
      if (!session) {
        setLanguage("en");
        return;
      }

      try {
        const response = await fetch(`${API_BASE}/api/profile/preferences`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!response.ok) {
          const error = new Error(`Preferences request failed (${response.status})`);
          error.status = response.status;
          throw error;
        }
        const preferences = await response.json();
        if (active && currentRevision === revision) {
          setLanguage(preferences.system_language || preferences.language || "en");
        }
      } catch (error) {
        if (active && error.status !== 401) {
          console.error("Could not load MIRA system language:", error);
        }
      }
    }

    const onLanguageChange = (event) => setLanguage(event.detail);
    window.addEventListener("mira-language-change", onLanguageChange);

    if (supabase) {
      supabase.auth.getSession()
        .then(({ data, error }) => {
          if (error) throw error;
          return loadLanguage(data.session);
        })
        .catch((error) => {
          if (active) console.error("Could not restore MIRA system language:", error);
        });
      const { data } = supabase.auth.onAuthStateChange((_event, session) => {
        loadLanguage(session);
      });
      return () => {
        active = false;
        data.subscription.unsubscribe();
        window.removeEventListener("mira-language-change", onLanguageChange);
      };
    }

    return () => {
      active = false;
      window.removeEventListener("mira-language-change", onLanguageChange);
    };
  }, [setLanguage]);

  const translateCurrentLanguage = useCallback(
    (key, values) => translate(languageRef.current, key, values),
    [],
  );
  const value = useMemo(() => ({
    language,
    setLanguage,
    t: translateCurrentLanguage,
  }), [language, setLanguage, translateCurrentLanguage]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error("useLanguage must be used within a LanguageProvider.");
  return context;
}
