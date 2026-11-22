"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import ArticleCard from "@/components/ArticleCard";
import { getCachedNews, putCachedNews } from "@/lib/newsCache";
import { supabase } from "@/lib/supabase";
import { useLanguage } from "@/components/LanguageProvider";

export default function Saved() {
  const { t } = useLanguage();
  const [favs, setFavs] = useState([]);
  const [needLogin, setNeedLogin] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [online, setOnline] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const updateOnline = () => setOnline(navigator.onLine);
    updateOnline();
    window.addEventListener("online", updateOnline);
    window.addEventListener("offline", updateOnline);
    return () => {
      window.removeEventListener("online", updateOnline);
      window.removeEventListener("offline", updateOnline);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadSaved() {
      async function hydrateFavorites(rows) {
        const hydrated = await Promise.all(rows.map(async (row) => {
          try {
            const cachedArticle = await getCachedNews(`article:${row.article_id}`);
            const article = {
              ...cachedArticle,
              ...row,
              id: row.article_id,
              image: row.image || cachedArticle?.image || cachedArticle?.image_url || null,
            };
            putCachedNews(`article:${row.article_id}`, article).catch((error) => {
              console.warn("Could not cache a saved story:", error);
            });
            return article;
          } catch (error) {
            console.warn("Could not update a saved story in the local cache:", error);
            return { ...row, id: row.article_id };
          }
        }));
        if (!cancelled) setFavs(hydrated);
        return hydrated;
      }

      let userId = null;
      try {
        const { data } = await supabase?.auth.getSession() || {};
        userId = data?.session?.user?.id || null;
      } catch (error) {
        console.warn("Could not identify the signed-in user for the local saved-story cache:", error);
      }
      if (userId) {
        try {
          const cachedFavorites = await getCachedNews(`favorites:${userId}`);
          if (!cancelled && cachedFavorites) await hydrateFavorites(cachedFavorites);
        } catch (error) {
          console.warn("Could not read cached saved stories:", error);
        }
      }
      if (!navigator.onLine) return;

      const favorites = await api("/api/favorites").then(
        (value) => ({ status: "fulfilled", value }),
        (reason) => ({ status: "rejected", reason }),
      );
      if (cancelled) return;

      if (favorites.status === "fulfilled") {
        const rows = favorites.value.favorites || [];
        const hydratedRows = await hydrateFavorites(rows);
        if (userId) {
          putCachedNews(`favorites:${userId}`, rows).catch((error) => {
            console.warn("Could not update cached saved stories:", error);
          });
        }
        for (const row of hydratedRows) {
          if (row.image || cancelled) continue;
          api(`/api/articles/${row.article_id}`).then((article) => {
            if (cancelled) return;
            const updatedArticle = { ...row, ...article, id: row.article_id };
            setFavs((current) => current.map((favorite) => (
              favorite.article_id === row.article_id ? updatedArticle : favorite
            )));
            putCachedNews(`article:${row.article_id}`, updatedArticle).catch((error) => {
              console.warn("Could not cache a saved story:", error);
            });
          }).catch((error) => {
            console.warn(`Could not load details for saved story ${row.article_id}:`, error);
          });
        }
      } else if (favorites.reason.status === 401) {
        setNeedLogin(true);
      } else if (!userId) {
        setLoadError(t("Couldn’t load saved stories: {message}", { message: t(favorites.reason.message) }));
      }
    }
    loadSaved();
    return () => { cancelled = true; };
  }, [online, t]);

  async function unsave(a) {
    await api(`/api/favorites/${a.article_id}`, { method: "DELETE" });
    setFavs((f) => f.filter((x) => x.article_id !== a.article_id));
  }

  const normalizedQuery = query.trim().toLowerCase();
  const filteredFavorites = favs.filter((item) => {
    if (!normalizedQuery) return true;
    return [item.title, item.summary, item.source, item.article_id]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedQuery));
  });
  if (needLogin) return <p>{t("Please")} <Link href="/login" className="underline">{t("Sign in")}</Link> {t("to see your saved articles and history.")}</p>;

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="label">{t("Your library")}</p>
          <h1 className="font-display text-3xl font-bold">{t("Saved articles")}</h1>
        </div>
        <label className="block w-full sm:ml-auto sm:max-w-sm">
          <span className="sr-only">{t("Search saved articles...")}</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="input"
            placeholder={t("Search saved articles...")}
          />
        </label>
      </header>

      {loadError && <p role="status" className="mt-3 text-sm text-amber-100">{loadError}</p>}

      <section aria-label={t("Saved articles")}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredFavorites.map((f, index) => (
            <ArticleCard
              key={f.article_id}
              article={{ ...f, id: f.article_id }}
              saved
              onSave={() => unsave(f)}
              priority={index === 0}
            />
          ))}
        </div>
        {favs.length === 0 && <p className="mt-4 text-white/70">{t("Nothing saved yet.")}</p>}
        {favs.length > 0 && filteredFavorites.length === 0 && (
          <p className="mt-4 text-white/70">{t("No saved articles match “{query}”.", { query: query.trim() })}</p>
        )}
      </section>
    </div>
  );
}
