"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLanguage } from "@/components/LanguageProvider";

export default function HistoryPage() {
  const { language, t } = useLanguage();
  const [history, setHistory] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [needLogin, setNeedLogin] = useState(false);
  const [activeTab, setActiveTab] = useState("history");
  const [query, setQuery] = useState("");

  useEffect(() => {
    Promise.allSettled([api("/api/history"), api("/api/conversations")]).then(([historyResult, conversationResult]) => {
      if (historyResult.status === "fulfilled") setHistory(historyResult.value.history || []);
      else if (historyResult.reason?.status === 401) setNeedLogin(true);
      if (conversationResult.status === "fulfilled") setConversations(conversationResult.value.conversations || []);
    });
  }, []);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredHistory = history.filter((item) =>
    [item.title, item.summary, item.source, item.article_id]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedQuery))
  );
  const filteredConversations = conversations.filter((item) =>
    [item.title, item.kind, item.article_id, item.created_at]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedQuery))
  );
  const dateLabel = (value) => {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const locale = language === "fil" ? "fil-PH" : language === "ceb" ? "ceb-PH" : "en-US";
    return date.toLocaleDateString(locale, { month: "short", day: "numeric", year: "numeric" });
  };

  if (needLogin) return (
    <p className="glass p-6">{t("Please")} <Link href="/login" className="underline">{t("Sign in")}</Link> {t("to view your reading history.")}</p>
  );

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      <header className="glass dashboard-hero">
        <div><p className="label">{t("Your activity")}</p><h1 className="font-display text-3xl font-bold">{t("History")}</h1></div>
      </header>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap justify-center gap-3" role="tablist" aria-label={t("History categories")}>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "history"}
            onClick={() => setActiveTab("history")}
            className={activeTab === "history" ? "btn" : "btn-ghost"}
          >
            {t("Reading history")} <span className="ml-1 text-white/70">({history.length})</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "conversations"}
            onClick={() => setActiveTab("conversations")}
            className={activeTab === "conversations" ? "btn" : "btn-ghost"}
          >
            {t("Reading conversations")} <span className="ml-1 text-white/70">({conversations.length})</span>
          </button>
        </div>
        <label className="mx-auto block w-full max-w-xl">
          <span className="sr-only">{t("Search this section")}</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="input"
            placeholder={activeTab === "history" ? t("Search reading history...") : t("Search reading conversations...")}
          />
        </label>
      </div>

      {activeTab === "history" ? (
        <section className="glass min-w-0 p-4 sm:p-5" role="tabpanel" aria-label={t("Reading history")}>
          <div className="home-section-heading">
            <h2>{t("Reading history")}</h2>
            <span className="text-xs text-white/50">{t("{count} stories", { count: filteredHistory.length })}</span>
          </div>
          {filteredHistory.length ? <div className="history-grid">
            {filteredHistory.map((item) => (
              <Link key={item.id || item.article_id} href={`/story/${item.article_id}`} className="history-card">
                <span className="flex justify-between gap-2 text-xs text-mira-blue-light">
                  <span>{item.source || "MIRA"}</span><time className="text-white/45">{dateLabel(item.viewed_at)}</time>
                </span>
                <strong>{item.title || t("Untitled article")}</strong>
                {item.summary && <p>{item.summary}</p>}
              </Link>
            ))}
          </div> : <p className="home-empty">{history.length ? t("No reading history matches “{query}”.", { query: query.trim() }) : t("No history yet.")}</p>}
        </section>
      ) : (
        <section className="glass min-w-0 p-4 sm:p-5" role="tabpanel" aria-label={t("Reading conversations")}>
          <div className="home-section-heading">
            <h2>{t("Reading conversations")}</h2>
            <span className="text-xs text-white/50">{t("{count} conversations", { count: filteredConversations.length })}</span>
          </div>
          {filteredConversations.length ? <div className="history-grid">
            {filteredConversations.map((item) => (
              <Link key={item.id} href={item.kind === "story" ? "/ask-story/history" : "/chat"} className="history-card">
                <span className="flex justify-between gap-2 text-xs text-mira-blue-light">
                  <span>{item.kind === "story" ? t("Story conversation") : t("AI chat")}</span>
                  <time className="text-white/45">{dateLabel(item.created_at)}</time>
                </span>
                <strong>{item.title || t("Untitled conversation")}</strong>
                {item.article_id && <span className="text-xs text-white/55">{t("View related story ↗")}</span>}
              </Link>
            ))}
          </div> : <p className="home-empty">{conversations.length ? t("No conversations match “{query}”.", { query: query.trim() }) : t("No conversations yet.")}</p>}
        </section>
      )}
    </div>
  );
}
