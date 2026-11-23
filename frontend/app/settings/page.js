"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useLanguage } from "@/components/LanguageProvider";

const LANGUAGES = [
  { value: "ceb", name: "Bisaya (Cebuano)" },
  { value: "fil", name: "Filipino (Tagalog)" },
  { value: "en", name: "English" },
];

const INTERESTS = [
  "Photojournalism",
  "Sports Journalism",
  "Mobile Journalism",
  "Media Arts",
  "Campus Journalism",
  "News Writing",
  "Feature Writing",
  "Editorial Writing",
  "Science and Technology",
  "Investigative Journalism",
  "Campus News Writing",
  "Campus Editorial Writing",
  "Campus Feature Writing",
  "Campus Sports Writing",
  "Campus Science and Technology Writing",
  "Campus Photojournalism",
  "Campus Copyreading and Headline Writing",
  "Campus Cartooning",
  "Campus Radio Broadcasting",
  "Campus TV Broadcasting",
  "Campus Collaborative Publishing",
  "Campus Online Publishing",
];

const NEWS_INTERESTS = [
  "Politics",
  "Health",
  "Sports",
  "Entertainment",
  "Technology",
  "Business",
  "Education",
  "Environment",
  "Agriculture",
  "Crime & Safety",
];

function activityDate(value, language, t) {
  const locale = language === "fil" ? "fil-PH" : language === "ceb" ? "ceb-PH" : "en-US";
  return value ? new Date(value).toLocaleString(locale) : t("Date unavailable");
}

export default function Settings() {
  const { language, setLanguage, t } = useLanguage();
  const [theme, setTheme] = useState("dark");
  const [systemLanguage, setSystemLanguage] = useState(language);
  const [aiLanguage, setAiLanguage] = useState("en");
  const [interests, setInterests] = useState([]);
  const [journalismFields, setJournalismFields] = useState([]);
  const [history, setHistory] = useState([]);
  const [searches, setSearches] = useState([]);
  const [favorites, setFavorites] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activityLoading, setActivityLoading] = useState(true);
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [activityError, setActivityError] = useState("");
  const [savingLanguage, setSavingLanguage] = useState(false);
  const [savingAiLanguage, setSavingAiLanguage] = useState(false);
  const [savingNews, setSavingNews] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [languageDirty, setLanguageDirty] = useState(false);
  const [aiLanguageDirty, setAiLanguageDirty] = useState(false);
  const [newsDirty, setNewsDirty] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [needLogin, setNeedLogin] = useState(false);
  const editedPreferences = useRef({ systemLanguage: false, aiLanguage: false, interests: {}, journalismFields: {} });
  const hasUnsavedChanges = languageDirty || aiLanguageDirty || newsDirty;

  useEffect(() => {
    const savedTheme = window.localStorage.getItem("mira-theme");
    setTheme(savedTheme === "light" ? "light" : "dark");
  }, []);

  function setAppearance(nextTheme) {
    const normalizedTheme = nextTheme === "light" ? "light" : "dark";
    setTheme(normalizedTheme);
    document.documentElement.dataset.miraTheme = normalizedTheme;
    window.localStorage.setItem("mira-theme", normalizedTheme);
    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) metaThemeColor.setAttribute("content", normalizedTheme === "light" ? "#f4f7fb" : "#000000");
  }

  useEffect(() => {
    if (!editedPreferences.current.systemLanguage) setSystemLanguage(language);
  }, [language]);

  useEffect(() => {
    let active = true;
    const loadingTimer = window.setTimeout(() => {
      if (active) setLoading(false);
    }, 1800);
    setLoading(true);
    setPreferencesLoaded(false);
    setError("");
    setActivityError("");
    setNeedLogin(false);
    setActivityLoading(true);
    api("/api/profile/preferences").then((preferences) => {
      if (!active) return;
      const savedSystemLanguage = preferences.system_language || preferences.language || "en";
      if (!editedPreferences.current.systemLanguage) {
        setSystemLanguage(savedSystemLanguage);
        setLanguage(savedSystemLanguage);
      }
      if (!editedPreferences.current.aiLanguage) setAiLanguage(preferences.ai_language || "en");
      const savedInterests = preferences.news_preferences || preferences.interests || [];
      setInterests(savedInterests.filter((value) => editedPreferences.current.interests[value] !== false)
        .concat(Object.keys(editedPreferences.current.interests).filter((value) => editedPreferences.current.interests[value] === true && !savedInterests.includes(value))));
      const savedFields = preferences.journalism_fields || [];
      setJournalismFields(savedFields.filter((value) => editedPreferences.current.journalismFields[value] !== false)
        .concat(Object.keys(editedPreferences.current.journalismFields).filter((value) => editedPreferences.current.journalismFields[value] === true && !savedFields.includes(value))));
      setPreferencesLoaded(true);
    }).catch((e) => {
      if (!active) return;
      if (e.status === 401) setNeedLogin(true);
      else setError(t("Couldn’t load your settings: {message}", { message: t(e.message) }));
    }).finally(() => {
      window.clearTimeout(loadingTimer);
      if (active) setLoading(false);
    });
    Promise.allSettled([
      api("/api/history"),
      api("/api/search-history"),
      api("/api/favorites"),
      api("/api/conversations"),
    ]).then((activity) => {
      if (!active) return;
      const [reading, searchHistory, saved, chats] = activity;
      if (reading.status === "fulfilled") setHistory(reading.value.history || []);
      if (searchHistory.status === "fulfilled") setSearches(searchHistory.value.searches || []);
      if (saved.status === "fulfilled") setFavorites(saved.value.favorites || []);
      if (chats.status === "fulfilled") setConversations(chats.value.conversations || []);
      if (activity.some((result) => result.status === "rejected")) {
        setActivityError(t("Some account activity could not be loaded."));
      }
    }).finally(() => { if (active) setActivityLoading(false); });
    return () => {
      active = false;
      window.clearTimeout(loadingTimer);
    };
  }, [loadAttempt, setLanguage, t]);

  useEffect(() => {
    if (!hasUnsavedChanges) return undefined;
    const warnBeforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const confirmNavigation = (event) => {
      if (!event.target.closest("a[href]")) return;
      if (!window.confirm(t("Discard unsaved changes?"))) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    document.addEventListener("click", confirmNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", warnBeforeUnload);
      document.removeEventListener("click", confirmNavigation, true);
    };
  }, [hasUnsavedChanges, t]);

  useEffect(() => {
    if (hasUnsavedChanges) document.documentElement.dataset.miraUnsavedSettings = "true";
    else delete document.documentElement.dataset.miraUnsavedSettings;
    return () => { delete document.documentElement.dataset.miraUnsavedSettings; };
  }, [hasUnsavedChanges]);

  const visibleError = error || activityError;

  if (needLogin) {
    return (
      <section className="glass mx-auto max-w-xl p-6">
        <h1 className="font-display text-2xl font-bold">{t("Sign in to Settings")}</h1>
        <p className="mt-2 text-sm text-white/70">{t("Your language preference, journalism interests, and history are saved to your account.")}</p>
        <Link href="/login" className="btn mt-4 inline-block">{t("Sign in")}</Link>
      </section>
    );
  }

  function toggleInterest(value) {
    const selected = !interests.includes(value);
    editedPreferences.current.interests[value] = selected;
    setInterests((current) => current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value]);
    setNewsDirty(true);
    setMessage("");
  }

  function toggleJournalismField(value) {
    if (!journalismFields.includes(value) && journalismFields.length >= 3) return;
    const selected = !journalismFields.includes(value);
    editedPreferences.current.journalismFields[value] = selected;
    setJournalismFields((current) => selected
      ? [...current, value]
      : current.filter((item) => item !== value));
    setNewsDirty(true);
    setMessage("");
  }

  async function saveLanguage() {
    setSavingLanguage(true);
    setError("");
    setMessage("");
    try {
      const result = await api("/api/profile/preferences", {
        method: "PUT",
        body: { system_language: systemLanguage },
      });
      const savedLanguage = result.system_language || result.language || systemLanguage;
      setSystemLanguage(savedLanguage);
      setLanguage(savedLanguage);
      setLanguageDirty(false);
      setMessage(t("systemLanguageSaved"));
    } catch (e) {
      setError(e.status === 401 ? t("signInToSave") : t("Couldn’t save preferences: {message}", { message: t(e.message) }));
    } finally {
      setSavingLanguage(false);
    }
  }

  async function saveAiLanguage() {
    setSavingAiLanguage(true);
    setError("");
    setMessage("");
    try {
      await api("/api/profile/preferences", {
        method: "PUT",
        body: { ai_language: aiLanguage },
      });
      setAiLanguageDirty(false);
      setMessage(t("aiLanguageSaved"));
    } catch (e) {
      setError(e.status === 401 ? t("signInToSave") : t("Couldn’t save preferences: {message}", { message: t(e.message) }));
    } finally {
      setSavingAiLanguage(false);
    }
  }

  async function saveNewsPreferences() {
    setSavingNews(true);
    setError("");
    setMessage("");
    try {
      const result = await api("/api/profile/preferences", {
        method: "PUT",
        body: { news_preferences: interests, journalism_fields: journalismFields },
      });
      setInterests(result.news_preferences);
      setJournalismFields(result.journalism_fields || []);
      setNewsDirty(false);
      setMessage(t("newsPreferencesSaved"));
    } catch (e) {
      setError(e.status === 401 ? t("signInToSave") : t("Couldn’t save preferences: {message}", { message: t(e.message) }));
    } finally {
      setSavingNews(false);
    }
  }

  async function clearHistory() {
    if (!window.confirm(t("Clear all viewed articles and search history? This cannot be undone."))) return;
    setClearing(true);
    setError("");
    try {
      await api("/api/history", { method: "DELETE" });
      setHistory([]);
      setSearches([]);
      setMessage(t("Your viewed-article and search history has been cleared."));
    } catch (e) {
      setError(e.status === 401 ? t("Sign in to clear your history.") : t("Couldn’t clear history: {message}", { message: t(e.message) }));
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header>
        <p className="label">{t("Your account")}</p>
        <h1 className="font-display text-3xl font-bold">{t("settings")}</h1>
        <p className="mt-1 text-sm text-white/65">{t("Manage the fields and topics that shape your recommendations, plus review your activity.")}</p>
      </header>

      {visibleError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-400/30 bg-red-950/30 p-3 text-sm text-red-200">
          <p>{visibleError}</p>
          <button type="button" className="btn-ghost !px-3 !py-1.5" onClick={() => {
            if (hasUnsavedChanges && !window.confirm(t("Discard unsaved changes?"))) return;
            editedPreferences.current = { systemLanguage: false, aiLanguage: false, interests: {}, journalismFields: {} };
            setLanguageDirty(false);
            setAiLanguageDirty(false);
            setNewsDirty(false);
            setLoadAttempt((attempt) => attempt + 1);
          }} disabled={loading}>
            {loading ? t("loading") : t("Retry")}
          </button>
        </div>
      )}
      {message && <p role="status" className="rounded-xl border border-emerald-400/20 bg-emerald-950/20 p-3 text-sm text-emerald-100">{message}</p>}
      <div className="space-y-6">
        <section id="appearance" className="glass p-5 sm:p-6">
          <h2 className="font-display text-xl font-bold">{t("Appearance")}</h2>
          <p className="mt-1 text-sm text-white/65">{t("Choose how MIRA looks on this device.")}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {[
              { value: "dark", label: "Dark", icon: "🌙" },
              { value: "light", label: "Light", icon: "☀️" },
            ].map((option) => (
              <label
                key={option.value}
                className={`flex cursor-pointer items-center gap-3 rounded-xl border p-4 text-sm ${
                  theme === option.value
                    ? "border-mira-blue-light bg-mira-blue/15"
                    : "border-white/10 bg-white/[.03]"
                }`}
              >
                <input
                  type="radio"
                  name="appearance"
                  value={option.value}
                  checked={theme === option.value}
                  onChange={() => setAppearance(option.value)}
                />
                <span className="text-xl" aria-hidden="true">{option.icon}</span>
                <span className="font-semibold">{t(option.label)}</span>
              </label>
            ))}
          </div>
        </section>

        <section id="language" className="glass p-5 sm:p-6">
          <h2 className="font-display text-xl font-bold">{t("language")}</h2>
          <h3 className="mt-4 font-semibold">{t("systemLanguage")}</h3>
          <p className="mt-1 text-sm text-white/65">{t("systemLanguageHelp")}</p>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            {LANGUAGES.map((option) => (
              <label key={option.value} className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 text-sm ${systemLanguage === option.value ? "border-mira-blue-light bg-mira-blue/15" : "border-white/10 bg-white/[.03]"}`}>
                <input type="radio" name="language" value={option.value} checked={systemLanguage === option.value}
                  disabled={savingLanguage}
                  onChange={() => { editedPreferences.current.systemLanguage = true; setSystemLanguage(option.value); setLanguageDirty(true); setMessage(""); }} />
                {t(option.name)}
              </label>
            ))}
          </div>
          <button className="btn mt-5" type="button" onClick={saveLanguage} disabled={savingLanguage || !languageDirty}>
            {savingLanguage ? t("saving") : t("saveSystemLanguage")}
          </button>

          <div className="mt-6 border-t border-white/10 pt-5">
            <h3 className="font-display text-lg font-bold">{t("aiLanguage")}</h3>
            <p className="mt-1 text-sm text-white/65">{t("aiLanguageHelp")}</p>
            <div className="mt-4 grid gap-2 sm:grid-cols-3">
              {LANGUAGES.map((option) => (
                <label key={option.value} className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 text-sm ${aiLanguage === option.value ? "border-mira-blue-light bg-mira-blue/15" : "border-white/10 bg-white/[.03]"}`}>
                  <input type="radio" name="ai-language" value={option.value} checked={aiLanguage === option.value}
                    disabled={savingAiLanguage}
                    onChange={() => { editedPreferences.current.aiLanguage = true; setAiLanguage(option.value); setAiLanguageDirty(true); setMessage(""); }} />
                  {t(option.name)}
                </label>
              ))}
            </div>
            <button className="btn mt-5" type="button" onClick={saveAiLanguage} disabled={savingAiLanguage || !aiLanguageDirty}>
              {savingAiLanguage ? t("saving") : t("saveAiLanguage")}
            </button>
          </div>
        </section>

        <section id="personalize" className="glass p-5 sm:p-6">
          <h2 className="font-display text-xl font-bold">{t("personalize")}</h2>
          <p className="mt-1 text-sm text-white/65">{t("personalizeHelp")}</p>
          <h3 className="mt-5 text-xs font-bold uppercase tracking-widest text-mira-blue-light">{t("journalismFields")} · {journalismFields.length}/3</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {INTERESTS.map((interest) => (
              <label key={interest} className={`chip cursor-pointer ${journalismFields.includes(interest) ? "chip-on" : ""}`}>
                <input className="sr-only" type="checkbox" checked={journalismFields.includes(interest)}
                  disabled={savingNews || (!journalismFields.includes(interest) && journalismFields.length >= 3)}
                  onChange={() => toggleJournalismField(interest)} />
                {t(interest)}
              </label>
            ))}
          </div>
          <h3 className="mt-5 text-xs font-bold uppercase tracking-widest text-mira-blue-light">{t("newsTopics")}</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {NEWS_INTERESTS.map((interest) => (
              <label key={interest} className={`chip cursor-pointer ${interests.includes(interest) ? "chip-on" : ""}`}>
                <input className="sr-only" type="checkbox" checked={interests.includes(interest)} disabled={savingNews}
                  onChange={() => toggleInterest(interest)} />
                {t(interest)}
              </label>
            ))}
          </div>
          <button className="btn mt-5" type="button" onClick={saveNewsPreferences} disabled={!preferencesLoaded || savingNews || !newsDirty}>
            {savingNews ? t("saving") : t("saveNewsPreferences")}
          </button>
        </section>
      </div>

      <section id="history" className="glass p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-bold">{t("history")}</h2>
            <p className="mt-1 text-sm text-white/65">{t("Review and revisit your recent reading and research activity.")}</p>
            {activityLoading && <p className="mt-2 text-xs text-white/50">{t("loading")}</p>}
          </div>
          <button className="btn-ghost" onClick={clearHistory} disabled={clearing || (!history.length && !searches.length)}>
            {clearing ? t("Clearing…") : t("Clear history")}
          </button>
        </div>
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-bold">{t("Previously viewed")}</h3>
            <ul className="divide-y divide-white/10">
              {history.map((item) => (
                <li key={item.id} className="py-2">
                  <Link className="block text-sm hover:underline" href={`/story/${item.article_id}`}>{item.title || t("Untitled article")}</Link>
                  <span className="text-xs text-white/50">{item.source || t("News")} · {activityDate(item.viewed_at, language, t)}</span>
                </li>
              ))}
            </ul>
            {!activityLoading && !history.length && <p className="text-sm text-white/55">{t("No viewed stories yet.")}</p>}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-bold">{t("Recent searches")}</h3>
            <ul className="divide-y divide-white/10">
              {searches.map((item) => (
                <li key={item.id} className="py-2">
                  <Link className="text-sm hover:underline" href={`/?q=${encodeURIComponent(item.query)}`}>{item.query}</Link>
                  <span className="ml-2 text-xs text-white/50">{activityDate(item.searched_at, language, t)}</span>
                </li>
              ))}
            </ul>
            {!activityLoading && !searches.length && <p className="text-sm text-white/55">{t("No searches yet.")}</p>}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-bold">{t("Saved and interacted-with stories")}</h3>
            <ul className="divide-y divide-white/10">
              {favorites.map((item) => (
                <li key={item.article_id} className="py-2">
                  <Link className="block text-sm hover:underline" href={`/story/${item.article_id}`}>{item.title || t("Untitled article")}</Link>
                  <span className="text-xs text-white/50">{item.source || t("News")} · {t("Saved")} {activityDate(item.saved_at, language, t)}</span>
                </li>
              ))}
            </ul>
            {!activityLoading && !favorites.length && <p className="text-sm text-white/55">{t("No saved stories yet.")}</p>}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-bold">{t("Past AI conversations")}</h3>
            <ul className="divide-y divide-white/10">
              {conversations.map((item) => (
                <li key={item.id} className="py-2 text-sm">
                  {item.kind === "story" ? `${t("Story")} · ` : `${t("Chat")} · `}{item.title || t("Research conversation")}
                  <span className="ml-2 text-xs text-white/50">{activityDate(item.created_at, language, t)}</span>
                </li>
              ))}
            </ul>
            {!activityLoading && !conversations.length && <p className="text-sm text-white/55">{t("No conversations yet.")}</p>}
          </div>
        </div>
      </section>
    </div>
  );
}
