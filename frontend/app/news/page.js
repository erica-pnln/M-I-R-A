"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useLanguage } from "@/components/LanguageProvider";
import {
  getCachedNews,
  getCachedNewsEntry,
  isNewsCacheFresh,
  newsCacheFreshInMs,
  newsRefreshIntervalMs,
  putCachedNews,
} from "@/lib/newsCache";
import ArticleCard from "@/components/ArticleCard";

const FEED_TABS = [
  { id: "all", title: "All" },
  { id: "trending", title: "Trending Stories" },
  { id: "international", title: "International" },
  { id: "national", title: "National" },
  { id: "regional", title: "Regional" },
  { id: "local", title: "Local" },
];

const NEWS_CATEGORIES = [
  "Business",
  "Sports",
  "Agriculture",
  "Politics",
  "Health",
  "Technology",
  "Education",
  "Environment",
  "Entertainment",
  "Crime & Safety",
];

function StorySection({
  title,
  description,
  articles,
  saved,
  onSave,
  empty,
  layout = "grid",
  initialCount = 4,
  onLoadMore,
  loadingMore = false,
  totalCount = articles.length,
  loading = false,
}) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useLanguage();
  const visibleArticles = expanded ? articles : articles.slice(0, initialCount);
  const hasMore = articles.length > initialCount;

  return (
    <section className={`dashboard-section ${layout === "list" ? "dashboard-news-panel glass p-4 sm:p-5" : ""}`}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-xl font-bold sm:text-2xl">{title}</h2>
          {description && <p className="mt-1 text-xs text-white/60">{description}</p>}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-white/50">
            {totalCount > articles.length
              ? t("{shown} of {total} stories", { shown: articles.length, total: totalCount })
              : t("{count} stories", { count: totalCount })}
          </span>
          {(hasMore || onLoadMore) && (
            <button
              className="text-xs font-bold text-mira-blue-light hover:text-white"
              onClick={() => {
                if (onLoadMore && !expanded && !hasMore) onLoadMore();
                else setExpanded((current) => !current);
              }}
              disabled={loadingMore}
            >
              {loadingMore ? t("loading") : expanded ? t("Show less") : t("View all")}
            </button>
          )}
        </div>
      </div>
      {articles.length ? (
        <div className={layout === "list" ? "grid grid-cols-2 gap-2.5" : "grid gap-3 sm:grid-cols-2 xl:grid-cols-3"}>
          {visibleArticles.map((article, index) => (
            <ArticleCard
              key={article.id}
              article={article}
              saved={saved.has(article.id)}
              onSave={onSave}
              compact={layout === "list"}
              priority={index === 0}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-white/10 bg-white/[.03] p-4 text-sm text-white/60">
          <p>{loading ? t("Loading stories…") : t(empty)}</p>
          {!loading && (
            <button
              type="button"
              className="btn-ghost mt-3 !px-3 !py-1.5 text-xs"
              onClick={() => window.location.reload()}
            >
              {t("Retry")}
            </button>
          )}
        </div>
      )}
      {onLoadMore && (
        <button
          className="btn-ghost mt-3 w-full !py-2 text-xs"
          onClick={() => {
            setExpanded(true);
            onLoadMore();
          }}
          disabled={loadingMore}
        >
          {loadingMore
            ? t("loading")
            : totalCount > articles.length
              ? t("Load more news ({count} remaining)", { count: totalCount - articles.length })
              : t("Load more news")}
        </button>
      )}
    </section>
  );
}

export default function Dashboard() {
  const { language, t } = useLanguage();
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [activeFeed, setActiveFeed] = useState("all");
  const [activeCategory, setActiveCategory] = useState("");
  const [categoryArticles, setCategoryArticles] = useState([]);
  const [categoryNextOffset, setCategoryNextOffset] = useState(null);
  const [categoryTotal, setCategoryTotal] = useState(0);
  const [categoryLoading, setCategoryLoading] = useState(false);
  const [searchInitialized, setSearchInitialized] = useState(false);
  const [dashboard, setDashboard] = useState({ trending: [], recommended: [], latest: [] });
  const [searchResults, setSearchResults] = useState([]);
  const [searchSuggestion, setSearchSuggestion] = useState("");
  const [searchNextOffset, setSearchNextOffset] = useState(null);
  const [saved, setSaved] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [online, setOnline] = useState(true);
  const [connectionIssue, setConnectionIssue] = useState(false);
  const [usingLocalCache, setUsingLocalCache] = useState(false);
  const [nextOffset, setNextOffset] = useState(null);
  const [error, setError] = useState("");
  const reconnected = useRef(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initialQuery = params.get("q") || "";
    const initialFeed = params.get("feed") || "";
    if (["trending", "international", "national", "regional", "local", "recommended"].includes(initialFeed)) {
      setActiveFeed(initialFeed);
    }
    setQueryInput(initialQuery);
    setQuery(initialQuery);
    setSearchInitialized(true);
  }, []);

  useEffect(() => {
    const handleOnline = () => {
      reconnected.current = true;
      setOnline(true);
    };
    const handleOffline = () => {
      reconnected.current = false;
      setOnline(false);
    };
    setOnline(navigator.onLine);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    api("/api/favorites")
      .then((result) => setSaved(new Set(result.favorites.map((favorite) => favorite.article_id))))
      .catch((e) => { if (e.status !== 401) setError(t("Couldn’t load saved stories: {message}", { message: t(e.message) })); });
  }, []);

  useEffect(() => {
    if (!searchInitialized || query) return undefined;
    let cancelled = false;
    let timer;
    let cachedDashboard = null;
    const cacheCategory = activeCategory || activeFeed;
    async function load(isPolling = false) {
      if (!isPolling) {
        setError("");
        setLoading(true);
        try {
          const entry = await getCachedNewsEntry("dashboard");
          cachedDashboard = entry?.value || null;
          if (!cancelled && cachedDashboard) {
            setDashboard(cachedDashboard);
            setNextOffset(cachedDashboard.next_offset);
            setRefreshing(false);
            setUsingLocalCache(true);
            setLoading(false);
            const cachedVisibleArticles = activeCategory
              ? []
              : activeFeed === "trending"
                ? cachedDashboard.trending || []
                : activeFeed === "recommended"
                  ? cachedDashboard.recommended || []
                  : cachedDashboard.latest || [];
            const cachedImagesMissing = cachedVisibleArticles
              .slice(0, 40)
              .some((article) => !article.image && !article.image_url);
            if (isNewsCacheFresh(entry, cacheCategory) && !reconnected.current) {
              if (cachedDashboard.image_enrichment_running) {
                timer = setTimeout(() => load(true), 15000);
                return;
              }
              if (!cachedImagesMissing) {
                timer = setTimeout(
                  () => load(true),
                  newsCacheFreshInMs(entry, cacheCategory),
                );
                return;
              }
            }
          }
        } catch (cacheError) {
          console.warn("Could not read cached MIRA headlines:", cacheError);
        }
      }
      if (!navigator.onLine) {
        setConnectionIssue(true);
        if (!cachedDashboard) setError(t("You’re offline and no cached headlines are available."));
        setLoading(false);
        return;
      }
      try {
        const result = await api("/api/dashboard?limit=100&offset=0");
        if (cancelled) return;
        const visibleResult = {
          ...result,
          trending: result.trending?.length ? result.trending : cachedDashboard?.trending || [],
          recommended: result.recommended?.length
            ? result.recommended
            : cachedDashboard?.recommended || [],
          latest: result.latest?.length ? result.latest : cachedDashboard?.latest || [],
          total: result.total || cachedDashboard?.total || 0,
          section_counts: result.section_counts || cachedDashboard?.section_counts || {},
          next_offset: result.next_offset ?? cachedDashboard?.next_offset ?? null,
        };
        setError((current) => current.includes("MIRA API") ? "" : current);
        setConnectionIssue(false);
        reconnected.current = false;
        setDashboard(visibleResult);
        setNextOffset(visibleResult.next_offset);
        setRefreshing(Boolean(visibleResult.refreshing));
        setUsingLocalCache(false);
        putCachedNews("dashboard", visibleResult).catch((cacheError) => {
          console.warn("Could not update cached MIRA headlines:", cacheError);
        });
        for (const article of [
          ...(visibleResult.latest || []),
          ...(visibleResult.trending || []),
          ...(visibleResult.recommended || []),
        ]) {
          putCachedNews(`article:${article.id}`, article).catch((cacheError) => {
            console.warn("Could not cache a MIRA article:", cacheError);
          });
        }
        timer = setTimeout(
          () => load(true),
          visibleResult.refreshing
            ? 1000
            : visibleResult.image_enrichment_running
              ? 15000
              : newsRefreshIntervalMs(cacheCategory),
        );
      } catch (e) {
        if (cancelled) return;
        setConnectionIssue(true);
        if (!cachedDashboard) setError(t(e.message));
        else timer = setTimeout(
          () => load(true),
          Math.min(30000, newsRefreshIntervalMs(cacheCategory)),
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, searchInitialized, online, activeCategory, activeFeed]);

  useEffect(() => {
    if (!searchInitialized || !query) return undefined;
    let cancelled = false;
    const params = new URLSearchParams({
      q: query,
      limit: "50",
      offset: "0",
    });
    if (activeFeed !== "all" && activeFeed !== "recommended") {
      params.set("section", activeFeed);
    }
    const cacheKey = `search:${query}:${activeFeed}`;
    setLoading(true);
    setSearchNextOffset(null);
    let cachedSearch = null;
    getCachedNews(cacheKey).catch((cacheError) => {
      console.warn("Could not read cached MIRA search results:", cacheError);
      return null;
    }).then((cached) => {
      cachedSearch = cached;
      if (!cancelled && cached) {
        setSearchResults(cached.articles || []);
        setSearchSuggestion(cached.corrected_query || "");
        setSearchNextOffset(cached.next_offset);
        setLoading(false);
      }
      if (!navigator.onLine) {
        setConnectionIssue(true);
        if (!cached) setError(t("You’re offline and no cached search results are available."));
        return null;
      }
      return api(`/api/search?${params}`);
    })
      .then((result) => {
        if (!result) return;
        if (cancelled) return;
        setSearchResults(result.articles || []);
        setSearchSuggestion(result.corrected_query || "");
        setSearchNextOffset(result.next_offset);
        setConnectionIssue(false);
        putCachedNews(cacheKey, result).catch((cacheError) => {
          console.warn("Could not update cached MIRA search results:", cacheError);
        });
        for (const article of result.articles || []) {
          putCachedNews(`article:${article.id}`, article).catch((cacheError) => {
            console.warn("Could not cache a MIRA article:", cacheError);
          });
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setConnectionIssue(true);
          if (!cachedSearch) setError(t("Couldn’t search stories: {message}", { message: t(e.message) }));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [query, searchInitialized, activeFeed, online]);

  useEffect(() => {
    const usesFilteredFeed = activeCategory || !["all", "recommended"].includes(activeFeed);
    if (!usesFilteredFeed || query) {
      setCategoryArticles([]);
      setCategoryTotal(0);
      setCategoryNextOffset(null);
      setCategoryLoading(false);
      return undefined;
    }
    let cancelled = false;
    const section = ["international", "national", "regional", "local"].includes(activeFeed)
      ? `&section=${activeFeed}`
      : activeFeed === "trending" ? "&section=trending" : "";
    const topic = activeCategory
      ? `&topic=${encodeURIComponent(activeCategory)}`
      : "";
    const cacheKey = `articles:v4:${section}:${topic}`;
    const cacheCategory = activeCategory || activeFeed;
    let cachedCategory = null;
    let timer;
    setCategoryArticles([]);
    function hydrateCachedCategoryImages(articles) {
      Promise.all(articles.slice(0, 40).map(async (article) => {
        if (article.image) return null;
        try {
          const cachedArticle = await getCachedNews(`article:${article.id}`);
          const image = cachedArticle?.image || cachedArticle?.image_url;
          return image ? [article.id, image] : null;
        } catch (cacheError) {
          console.warn("Could not hydrate a cached category image:", cacheError);
          return null;
        }
      })).then((cachedImages) => {
        if (cancelled) return;
        const imagesById = new Map(cachedImages.filter(Boolean));
        if (!imagesById.size) return;
        setCategoryArticles((current) => current.map((article) => (
          !article.image && imagesById.has(article.id)
            ? { ...article, image: imagesById.get(article.id) }
            : article
        )));
      });
    }
    async function load(force = false) {
      setCategoryLoading(true);
      try {
        let entry = null;
        if (!force) {
          try {
            entry = await getCachedNewsEntry(cacheKey);
            cachedCategory = entry?.value || null;
          } catch (cacheError) {
            console.warn("Could not read cached category headlines:", cacheError);
          }
          if (!cancelled && cachedCategory) {
            setCategoryArticles(cachedCategory.articles || []);
            setCategoryTotal(cachedCategory.total || 0);
            setCategoryNextOffset(cachedCategory.next_offset);
            hydrateCachedCategoryImages(cachedCategory.articles || []);
          }
          if (isNewsCacheFresh(entry, cacheCategory) && !reconnected.current) {
            if (cachedCategory?.image_enrichment_running) {
              timer = setTimeout(() => load(true), 15000);
              return;
            }
            if (!cachedCategory?.articles?.some((article) => !article.image)) {
              timer = setTimeout(
                () => load(true),
                newsCacheFreshInMs(entry, cacheCategory),
              );
              return;
            }
          }
        }
        if (!navigator.onLine) {
          setConnectionIssue(true);
          if (!cachedCategory) {
            setError(t("You’re offline and no cached {section} stories are available.", { section: t(activeCategory || activeFeed) }));
          }
          return;
        }
        const result = await api(`/api/articles?limit=100&offset=0${section}${topic}`);
        if (cancelled) return;
        const articles = result.articles?.length
          ? result.articles
          : cachedCategory?.articles || [];
        const visibleResult = { ...result, articles };
        setCategoryArticles(articles);
        setCategoryTotal(visibleResult.total || cachedCategory?.total || 0);
        setCategoryNextOffset(visibleResult.next_offset ?? cachedCategory?.next_offset ?? null);
        setConnectionIssue(false);
        reconnected.current = false;
        putCachedNews(cacheKey, visibleResult).catch((cacheError) => {
          console.warn("Could not update cached category headlines:", cacheError);
        });
        for (const article of articles) {
          putCachedNews(`article:${article.id}`, article).catch((cacheError) => {
            console.warn("Could not cache a MIRA article:", cacheError);
          });
        }
        timer = setTimeout(
          () => load(true),
          result.refreshing
            ? 1000
            : result.image_enrichment_running
              ? 15000
              : newsRefreshIntervalMs(cacheCategory),
        );
      } catch (e) {
        if (!cancelled) {
          setConnectionIssue(true);
          if (!cachedCategory) {
            setError(t("Couldn’t load {section} stories: {message}", { section: t(activeCategory || activeFeed), message: t(e.message) }));
          }
          timer = setTimeout(
            () => load(true),
            Math.min(30000, newsRefreshIntervalMs(cacheCategory)),
          );
        }
      } finally {
        if (!cancelled) setCategoryLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [activeCategory, activeFeed, query, online]);

  async function toggleSave(article) {
    try {
      if (saved.has(article.id)) {
        await api(`/api/favorites/${article.id}`, { method: "DELETE" });
        setSaved((current) => {
          const next = new Set(current);
          next.delete(article.id);
          return next;
        });
      } else {
        await api("/api/favorites", { method: "POST", body: article });
        setSaved((current) => new Set(current).add(article.id));
      }
    } catch (e) {
      if (e.status === 401) window.location.href = "/login";
      else setError(t("Couldn’t update saved stories: {message}", { message: t(e.message) }));
    }
  }

  async function loadMore() {
    if (query) {
      if (searchNextOffset === null || loadingMore) return;
      setLoadingMore(true);
      try {
        const params = new URLSearchParams({
          q: query,
          limit: "50",
          offset: String(searchNextOffset),
        });
        if (activeFeed !== "all" && activeFeed !== "recommended") {
          params.set("section", activeFeed);
        }
        const result = await api(`/api/search?${params}`);
        const mergedResults = [...searchResults, ...(result.articles || [])];
        setSearchResults(mergedResults);
        setSearchNextOffset(result.next_offset);
        putCachedNews(`search:${query}:${activeFeed}`, {
          ...result,
          articles: mergedResults,
        }).catch((cacheError) => {
          console.warn("Could not update cached MIRA search results:", cacheError);
        });
        for (const article of result.articles || []) {
          putCachedNews(`article:${article.id}`, article).catch((cacheError) => {
            console.warn("Could not cache a MIRA article:", cacheError);
          });
        }
      } catch (e) {
        setError(t("Couldn’t load more search results: {message}", { message: t(e.message) }));
      } finally {
        setLoadingMore(false);
      }
      return;
    }
    const usesFilteredFeed = activeCategory || !["all", "recommended"].includes(activeFeed);
    if ((usesFilteredFeed ? categoryNextOffset : nextOffset) === null || loadingMore) return;
    setLoadingMore(true);
    try {
      if (usesFilteredFeed && categoryNextOffset !== null) {
        const section = ["international", "national", "regional", "local"].includes(activeFeed)
          ? `&section=${activeFeed}`
          : activeFeed === "trending" ? "&section=trending" : "";
        const topic = activeCategory
          ? `&topic=${encodeURIComponent(activeCategory)}`
          : "";
        const result = await api(
          `/api/articles?limit=100&offset=${categoryNextOffset}${section}${topic}`
        );
        const mergedArticles = [...categoryArticles, ...(result.articles || [])];
        setCategoryArticles(mergedArticles);
        setCategoryNextOffset(result.next_offset);
        const cacheKey = `articles:v4:${section}:${topic}`;
        putCachedNews(cacheKey, { ...result, articles: mergedArticles }).catch((cacheError) => {
          console.warn("Could not update cached category headlines:", cacheError);
        });
        for (const article of result.articles || []) {
          putCachedNews(`article:${article.id}`, article).catch((cacheError) => {
            console.warn("Could not cache a MIRA article:", cacheError);
          });
        }
      } else {
        const result = await api(`/api/dashboard?limit=100&offset=${nextOffset}`);
        const updatedDashboard = {
          ...dashboard,
          latest: [...dashboard.latest, ...result.latest],
          trending: [...dashboard.trending, ...result.trending],
          next_offset: result.next_offset,
        };
        setDashboard(updatedDashboard);
        setNextOffset(result.next_offset);
        putCachedNews("dashboard", updatedDashboard).catch((cacheError) => {
          console.warn("Could not update cached MIRA headlines:", cacheError);
        });
        for (const article of [...(result.latest || []), ...(result.trending || [])]) {
          putCachedNews(`article:${article.id}`, article).catch((cacheError) => {
            console.warn("Could not cache a MIRA article:", cacheError);
          });
        }
      }
    } catch (e) {
      setError(t("Couldn’t load more stories: {message}", { message: t(e.message) }));
    } finally {
      setLoadingMore(false);
    }
  }

  function search(event) {
    event.preventDefault();
    const nextQuery = queryInput.trim();
    setSearchSuggestion("");
    setSearchResults([]);
    window.history.replaceState(null, "", nextQuery ? `/?q=${encodeURIComponent(nextQuery)}` : "/");
    setQuery(nextQuery);
  }

  const feedTabs = dashboard.has_activity
    ? query
      ? FEED_TABS
      : [...FEED_TABS, { id: "recommended", title: t("recommended") }]
    : FEED_TABS;
  const activeTab = feedTabs.find((tab) => tab.id === activeFeed) || FEED_TABS[0];
  const feedArticles = activeFeed === "trending"
    ? dashboard.trending
    : activeFeed === "recommended"
      ? dashboard.recommended
      : activeFeed === "all"
        ? dashboard.latest
        : dashboard.latest.filter((article) => article.section === activeFeed);
  const usesFilteredFeed = activeCategory || !["all", "recommended"].includes(activeFeed);
  const activeArticles = usesFilteredFeed
    ? categoryArticles
    : feedArticles;
  const sectionDescription = {
    all: t("The newest reports from all supported sources."),
    trending: t("Trending reports, with local and regional coverage first."),
    international: t("The latest reports from international sources."),
    national: t("The latest reports from across the Philippines."),
    regional: t("The latest reports from across Mindanao and nearby regions."),
    local: t("The latest reports from Caraga and nearby communities."),
    recommended: t("Selected interests, reading history, and saved stories shape these picks."),
  }[activeFeed] || "";

  return (
    <div className="space-y-7">
      <section className="newsroom-hero glass" aria-labelledby="newsroom-title">
        <div className="newsroom-heading">
          <div className="newsroom-kicker">
            <span className="newsroom-live-dot" aria-hidden="true" />
            <span>{t("MIRA Newsroom")}</span>
            <span className="newsroom-kicker-line" aria-hidden="true" />
            <span>{t("Live intelligence")}</span>
          </div>
          <h1 id="newsroom-title" className="font-display">
            {t("The stories shaping")} <span>{t("today.")}</span>
          </h1>
          <p>{t("Explore verified reports, emerging trends, and regional perspectives.")}</p>
        </div>

        <div className="newsroom-tools">
          <form className="newsroom-search" role="search" onSubmit={search}>
            <span className="newsroom-search-icon" aria-hidden="true">⌕</span>
            <input
              aria-label={t("Search stories, topics, and sources")}
              placeholder={t("Search stories, topics, sources…")}
              value={queryInput}
              onChange={(event) => setQueryInput(event.target.value)}
            />
            {query && (
              <button
                className="newsroom-clear"
                type="button"
                aria-label={t("Clear")}
                onClick={() => {
                  window.history.replaceState(null, "", "/");
                  setQuery("");
                  setQueryInput("");
                }}
              >
                ×
              </button>
            )}
            <button className="newsroom-search-button" type="submit">{t("Search")}</button>
          </form>
          <div className="newsroom-sync" role="status">
            <span className={`newsroom-sync-state ${online && !connectionIssue ? "is-live" : "is-offline"}`}>
              {online && !connectionIssue ? t("Feed live") : t("Offline mode")}
            </span>
            <span>
              {!online || connectionIssue
                ? activeArticles.length
                  ? t("Showing cached headlines")
                  : t("No cached headlines available")
                : usingLocalCache
                  ? t("Checking for new reports")
                  : t("Latest reports from MIRA")}
            </span>
          </div>
        </div>
      </section>

      {error && <p role="alert" className="rounded-xl border border-red-400/30 bg-red-950/30 p-3 text-sm text-red-200">{error}</p>}
      {loading && !dashboard.latest.length && !searchResults.length && (
        <p className="animate-pulse rounded-2xl bg-white/[.04] p-5 text-sm text-white/70">{t("Loading cached headlines…")}</p>
      )}
      {!loading && refreshing && <p className="text-xs text-white/55">{t("Updating headlines in the background…")}</p>}
      <>
          {!query && (
            <nav
              className="news-category-tabs flex w-full flex-nowrap justify-start gap-1.5 overflow-x-auto pb-2"
              aria-label={t("News categories")}
              role="tablist"
            >
              <button
                type="button"
                role="tab"
                aria-selected={!activeCategory}
                className={`shrink-0 rounded-full px-3 py-1.5 text-sm font-bold transition ${
                  !activeCategory ? "bg-mira-blue text-white" : "border border-white/10 bg-white/[.04] text-white/65 hover:bg-white/10 hover:text-white"
                }`}
                onClick={() => setActiveCategory("")}
              >
                {t("Top categories")}
              </button>
              {NEWS_CATEGORIES.map((category) => (
                <button
                  key={category}
                  type="button"
                  role="tab"
                  aria-selected={activeCategory === category}
                  className={`shrink-0 rounded-full px-3 py-1.5 text-sm font-bold transition ${
                    activeCategory === category ? "bg-mira-blue text-white" : "border border-white/10 bg-white/[.04] text-white/65 hover:bg-white/10 hover:text-white"
                  }`}
                  onClick={() => setActiveCategory(category)}
                >
                  {t(category)}
                </button>
              ))}
            </nav>
          )}
          <nav
            className="flex flex-wrap justify-center gap-2 rounded-2xl border border-white/10 bg-white/[.03] p-2"
            aria-label={t("Filter news")}
            role="tablist"
          >
            {feedTabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeFeed === tab.id}
                className={`shrink-0 rounded-full px-4 py-2 text-base font-bold transition ${
                  activeFeed === tab.id
                    ? "bg-mira-blue text-white"
                    : "text-white/65 hover:bg-white/10 hover:text-white"
                }`}
                onClick={() => setActiveFeed(tab.id)}
              >
                {t(tab.title)}
              </button>
            ))}
          </nav>
          {query ? (
            <StorySection
              title={t("Search results for “{query}”", { query: searchSuggestion || query })}
              description={[
                searchSuggestion ? `Closest spelling match for “${query}”.` : "",
                t(activeTab.title),
              ].filter(Boolean).join("  •  ")}
              articles={searchResults}
              saved={saved}
              onSave={toggleSave}
              initialCount={50}
              totalCount={searchResults.length}
              onLoadMore={searchNextOffset !== null ? loadMore : undefined}
              loadingMore={loadingMore}
              empty="No stories match these search filters. Try another keyword or filter."
              loading={loading}
            />
          ) : (
            <StorySection
              title={activeCategory ? `${t(activeCategory)} · ${t(activeTab.title)}` : t(activeTab.title)}
            description={sectionDescription}
            articles={activeArticles}
            saved={saved}
            onSave={toggleSave}
            totalCount={activeCategory
              ? categoryTotal
              : !["all", "recommended"].includes(activeFeed)
                ? categoryTotal
              : activeFeed === "trending"
                ? dashboard.section_counts
                  ? Object.values(dashboard.section_counts).reduce((total, count) => total + count, 0)
                  : dashboard.total
                : activeFeed === "all" || activeFeed === "recommended"
                  ? activeFeed === "recommended" ? dashboard.recommended.length : dashboard.total
                  : dashboard.section_counts?.[activeFeed] ?? activeArticles.length}
            empty={activeFeed === "recommended"
              ? "Your activity is recorded. Read or save a few articles, or select interests in Settings, to build recommendations."
              : "No stories are available in this section right now."}
            initialCount={40}
            onLoadMore={
              activeFeed === "recommended"
                ? undefined
                : usesFilteredFeed
                  ? categoryNextOffset !== null ? loadMore : undefined
                  : nextOffset !== null ? loadMore : undefined
            }
            loadingMore={loadingMore}
            loading={categoryLoading}
          />
          )}
      </>
    </div>
  );
}
