"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useLanguage } from "@/components/LanguageProvider";

const PAGE_SIZE = 100;

function formatDate(value, language) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  const locale = language === "fil" ? "fil-PH" : language === "ceb" ? "ceb-PH" : "en-US";
  return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleString(locale);
}

export default function AskStoryHistory() {
  const { language, t } = useLanguage();
  const [conversations, setConversations] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [signInRequired, setSignInRequired] = useState(false);

  const loadPage = useCallback(async (nextOffset, append) => {
    try {
      const result = await api(
        `/api/ask/conversations?limit=${PAGE_SIZE}&offset=${nextOffset}`,
      );
      setConversations((current) => append
        ? [...current, ...(result.conversations || [])]
        : result.conversations || []);
      setOffset(nextOffset);
      setHasMore(Boolean(result.has_more));
      setError("");
    } catch (requestError) {
      if (requestError.status === 401) {
        setSignInRequired(true);
        setError("");
      } else {
        setError(t("Couldn’t load Ask Story history: {message}", { message: t(requestError.message) }));
      }
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [t]);

  useEffect(() => {
    loadPage(0, false);
  }, [loadPage]);

  async function openConversation(conversation) {
    setSelected(conversation);
    setMessages([]);
    setError("");
    try {
      const result = await api(`/api/ask/conversations/${conversation.id}`);
      setSelected(result.conversation);
      setMessages(result.messages || []);
    } catch (requestError) {
      setError(t("Couldn’t open this conversation: {message}", { message: t(requestError.message) }));
    }
  }

  return (
    <div className="space-y-5">
      <header className="glass p-5 sm:p-6">
        <Link href="/" className="btn-ghost inline-block">← {t("Dashboard")}</Link>
        <p className="label mt-5">{t("Your research conversations")}</p>
        <h1 className="font-display text-3xl font-bold">{t("Ask Story history")}</h1>
        <p className="mt-2 text-sm text-white/65">{t("Revisit questions and responses about news stories you explored.")}</p>
      </header>

      {error && (
        <p role="alert" className="rounded-xl border border-red-400/30 bg-red-950/30 p-3 text-sm text-red-200">
          {error}
        </p>
      )}

      {signInRequired ? (
        <section className="glass p-6">
          <h2 className="font-display text-xl font-bold">{t("Sign in to view your history")}</h2>
          <p className="mt-2 text-sm text-white/65">
            {t("Ask Story conversations are saved to your account so only you can review them.")}
          </p>
          <Link href="/login" className="btn mt-4 inline-block">{t("Sign in")}</Link>
        </section>
      ) : (
        <div className="grid min-h-[32rem] gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <aside className="glass flex min-h-0 flex-col p-3">
            <h2 className="px-3 py-2 text-xs font-bold uppercase tracking-wider text-white/55">
              {t("Saved conversations")}
            </h2>
            <div className="max-h-[70vh] flex-1 space-y-1 overflow-y-auto">
              {conversations.map((conversation) => (
                <button
                  type="button"
                  key={conversation.id}
                  onClick={() => openConversation(conversation)}
                  className={`w-full rounded-xl px-3 py-3 text-left hover:bg-white/[.06] ${
                    selected?.id === conversation.id ? "bg-mira-blue/25" : ""
                  }`}
                >
                  <span className="block line-clamp-2 text-sm font-medium">
                    {conversation.title || t("Ask Story conversation")}
                  </span>
                  <span className="mt-1 block text-xs text-white/45">
                    {formatDate(conversation.created_at, language)}
                  </span>
                </button>
              ))}
              {!loading && conversations.length === 0 && (
                <p className="px-3 py-4 text-sm text-white/55">
                  {t("No saved Ask Story conversations yet. Sign in and ask a question about a story to save it here.")}
                </p>
              )}
            </div>
            {hasMore && (
              <button
                type="button"
                className="btn-ghost mt-2 w-full"
                disabled={loadingMore}
                onClick={() => {
                  setLoadingMore(true);
                  loadPage(offset + PAGE_SIZE, true);
                }}
              >
                {loadingMore ? t("loading") : t("Load older conversations")}
              </button>
            )}
          </aside>

          <section className="glass min-w-0 p-4 sm:p-6">
            {loading ? (
              <p className="text-sm text-white/60">{t("Loading your saved conversations…")}</p>
            ) : selected ? (
              <>
                <div className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b border-white/10 pb-4">
                  <div>
                    <h2 className="font-display text-xl font-bold">{selected.title}</h2>
                    <p className="mt-1 text-xs text-white/50">
                      {t("Started {date}", { date: formatDate(selected.created_at, language) })}
                    </p>
                  </div>
                  {selected.article_id && (
                    <Link className="btn-ghost" href={`/story/${encodeURIComponent(selected.article_id)}`}>
                      {t("View selected story")}
                    </Link>
                  )}
                </div>
                <div className="space-y-3">
                  {messages.map((message) => (
                    <article
                      key={message.id}
                      className={`max-w-[95%] whitespace-pre-wrap break-words rounded-2xl border px-4 py-3 text-sm leading-relaxed ${
                        message.role === "user"
                          ? "ml-auto border-white/20 bg-mira-blue/30"
                          : "border-white/10 bg-white/[.05]"
                      }`}
                    >
                      <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-white/45">
                        {message.role === "user" ? t("You") : "Ask Story"} · {formatDate(message.created_at, language)}
                      </p>
                      {message.content}
                    </article>
                  ))}
                  {!messages.length && (
                    <p className="text-sm text-white/55">{t("This conversation has no saved messages.")}</p>
                  )}
                </div>
              </>
            ) : (
              <p className="text-sm text-white/55">
                {loading ? t("loading") : t("Select a conversation to review its messages.")}
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
