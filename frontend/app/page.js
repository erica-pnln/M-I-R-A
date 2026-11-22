"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getCachedNews, putCachedNews } from "@/lib/newsCache";
import ArticleCard from "@/components/ArticleCard";
import ArticleImage from "@/components/ArticleImage";
import MediaPreview from "@/components/MediaPreview";
import { getDirectEpisodeUrl, getDirectLivePageUrl, getDirectLiveUrl } from "@/lib/media";

export default function Home() {
  const [query, setQuery] = useState("");
  const [dashboard, setDashboard] = useState({ latest: [], trending: [], section_counts: {} });
  const [podcasts, setPodcasts] = useState([]);
  const [liveChannels, setLiveChannels] = useState([]);
  const [regional, setRegional] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savedIds, setSavedIds] = useState(new Set());
  const [activeTrendingIndex, setActiveTrendingIndex] = useState(0);
  const [isTrendingPaused, setIsTrendingPaused] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const readCache = (key) => getCachedNews(key).catch((error) => {
      console.warn(`Could not read cached MIRA home data (${key}):`, error);
      return null;
    });
    const writeCache = (key, value) => {
      putCachedNews(key, value).catch((error) => {
        console.warn(`Could not save cached MIRA home data (${key}):`, error);
      });
    };

    async function loadHome() {
      const [cachedHomeDashboard, cachedNewsDashboard, cachedPodcasts, cachedLive, cachedRegional] = await Promise.all([
        readCache("home:dashboard"),
        readCache("dashboard"),
        readCache("home:podcasts"),
        readCache("live:channels"),
        readCache("home:regional"),
      ]);
      if (cancelled) return;

      const localDashboard = cachedHomeDashboard || cachedNewsDashboard;
      if (localDashboard) {
        setDashboard(localDashboard);
        setLoading(false);
      }
      if (cachedPodcasts) setPodcasts(cachedPodcasts.episodes || []);
      if (cachedLive) setLiveChannels(cachedLive.channels || []);
      if (cachedRegional) setRegional(cachedRegional.articles || []);

      if (!navigator.onLine) {
        setLoading(false);
        return;
      }

      const results = await Promise.allSettled([
        api("/api/dashboard?limit=30&offset=0"),
        api("/api/podcasts?limit=4"),
        api("/api/live"),
        api("/api/articles?section=regional&limit=10&offset=0"),
      ]);
      if (cancelled) return;

      const [newsResult, podcastResult, liveResult, regionalResult] = results;
      if (newsResult.status === "fulfilled") {
        setDashboard(newsResult.value);
        writeCache("home:dashboard", newsResult.value);
      }
      if (podcastResult.status === "fulfilled") {
        setPodcasts(podcastResult.value.episodes || []);
        writeCache("home:podcasts", podcastResult.value);
      }
      if (liveResult.status === "fulfilled") {
        setLiveChannels(liveResult.value.channels || []);
        writeCache("live:channels", liveResult.value);
      }
      if (regionalResult.status === "fulfilled") {
        setRegional(regionalResult.value.articles || []);
        writeCache("home:regional", regionalResult.value);
      }
      setLoading(false);
    }

    loadHome();
    api("/api/favorites")
      .then((result) => setSavedIds(new Set((result.favorites || []).map((item) => item.article_id))))
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  function search(event) {
    event.preventDefault();
    const value = query.trim();
    if (value) window.location.assign(`/news?q=${encodeURIComponent(value)}`);
  }

  async function toggleSaved(article) {
    const isSaved = savedIds.has(article.id);
    try {
      if (isSaved) {
        await api(`/api/favorites/${article.id}`, { method: "DELETE" });
        setSavedIds((current) => {
          const next = new Set(current);
          next.delete(article.id);
          return next;
        });
      } else {
        await api("/api/favorites", { method: "POST", body: article });
        setSavedIds((current) => new Set(current).add(article.id));
      }
    } catch (error) {
      console.warn("Could not update saved state:", error);
    }
  }

  const topNews = (dashboard.latest || []).slice(0, 3);
  const trending = (dashboard.trending || dashboard.latest || []).slice(0, 5);
  const imageTrending = (dashboard.trending || []).filter((article) => article.image).slice(0, 5);
  const trendingSlides = imageTrending.length
    ? imageTrending
    : (dashboard.latest || []).filter((article) => article.image).slice(0, 5);
  const activeTrending = trendingSlides[activeTrendingIndex % (trendingSlides.length || 1)];

  useEffect(() => {
    if (isTrendingPaused || trendingSlides.length < 2 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;
    const timer = window.setInterval(() => {
      setActiveTrendingIndex((index) => (index + 1) % trendingSlides.length);
    }, 6500);
    return () => window.clearInterval(timer);
  }, [isTrendingPaused, trendingSlides.length]);

  return (
    <div className="home-dashboard">
      <section
        className="home-hero home-hero-showcase glass"
        role="region"
        aria-roledescription="carousel"
        aria-label="Trending stories"
        onMouseEnter={() => setIsTrendingPaused(true)}
        onMouseLeave={() => setIsTrendingPaused(false)}
        onFocusCapture={() => setIsTrendingPaused(true)}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setIsTrendingPaused(false);
        }}
      >
        <div className="home-hero-backdrop" aria-hidden="true">
          {activeTrending && (
            <ArticleImage
              key={activeTrending.id}
              article={activeTrending}
              className="home-hero-image"
              priority
            />
          )}
        </div>
        <div className="home-hero-copy">
          <p className="label">{activeTrending ? "Trending now" : "Media Intelligence & Research Assistant"}</p>
          <h1 className="font-display text-4xl font-bold leading-tight sm:text-5xl">
            {activeTrending?.title || "Go Beyond the Headline."}
          </h1>
        </div>
        <div className="home-hero-actions">
          <form onSubmit={search} className="home-search" role="search">
            <span aria-hidden="true">⌕</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search news, topics, events, or issues"
              aria-label="Search news"
              className="min-w-0 flex-1 bg-transparent outline-none"
            />
            <button type="submit" aria-label="Search">→</button>
          </form>
          {trendingSlides.length > 1 && (
            <div className="home-hero-controls">
              <button
                type="button"
                onClick={() => setActiveTrendingIndex((index) => (index - 1 + trendingSlides.length) % trendingSlides.length)}
                aria-label="Previous trending story"
              >
                ←
              </button>
              <span aria-live="polite">{(activeTrendingIndex % trendingSlides.length) + 1} / {trendingSlides.length}</span>
              <button
                type="button"
                onClick={() => setActiveTrendingIndex((index) => (index + 1) % trendingSlides.length)}
                aria-label="Next trending story"
              >
                →
              </button>
            </div>
          )}
        </div>
      </section>

      <div className="home-grid-main">
        <section className="home-panel glass">
          <div className="home-section-heading">
            <h2><span aria-hidden="true">▤</span> Top News</h2>
            <Link href="/news">See all →</Link>
          </div>
          {loading ? <p className="home-empty">Loading top stories…</p> : topNews.length ? (
            <div className="home-top-news">
              {topNews.map((article, index) => (
                <ArticleCard
                  key={article.id}
                  article={article}
                  saved={savedIds.has(article.id)}
                  onSave={toggleSaved}
                  compact
                  priority={index === 0}
                />
              ))}
            </div>
          ) : <p className="home-empty">No verified news stories are available right now.</p>}
        </section>

        <section className="home-panel home-panel-media glass">
          <div className="home-section-heading">
            <h2><span aria-hidden="true">◉</span> Live Updates</h2>
            <Link href="/live">See all →</Link>
          </div>
          <div className="home-live-preview">
            {liveChannels.length ? (
              liveChannels.slice(0, 3).map((channel) => {
                const destination = getDirectLiveUrl(channel.url, channel.is_live === true)
                  || getDirectLivePageUrl(channel.live_page_url || channel.source_url);
                const content = (
                  <>
                    <MediaPreview
                      kind="live"
                      image={channel.image || channel.channel_image}
                      publisher={channel.publisher}
                      title={channel.title}
                      isLive={channel.is_live === true}
                      className="home-live-placeholder"
                    />
                    <span className="home-live-copy">
                      <strong>{channel.title}</strong>
                      <small>{channel.publisher}</small>
                    </span>
                  </>
                );
                return destination ? (
                  <a key={channel.url || `${channel.publisher}-${channel.title}`} href={destination} target="_blank" rel="noreferrer" className="home-live-item">
                    {content}
                  </a>
                ) : (
                  <div key={channel.url || `${channel.publisher}-${channel.title}`} className="home-live-item">
                    {content}
                  </div>
                );
              })
            ) : (
              <MediaPreview
                kind="live"
                publisher="Official broadcaster feeds"
                title="Trusted live coverage directory"
                className="home-live-placeholder"
              />
            )}
            <p>{liveChannels.length ? "Open trusted Philippine and international channels for live coverage." : "Loading trusted Philippine and international live channels…"}</p>
            <Link href="/live" className="btn-ghost !px-4 !py-2 text-xs">Watch Live</Link>
          </div>
        </section>

        <section className="home-panel home-panel-media glass">
          <div className="home-section-heading">
            <h2><span aria-hidden="true">♫</span> Podcast</h2>
            <Link href="/podcast">See all →</Link>
          </div>
          {podcasts.length ? (
            <div className="home-podcast-list">
              {podcasts.slice(0, 4).map((episode) => (
                getDirectEpisodeUrl(episode.url) ? (
                  <a key={episode.id} href={getDirectEpisodeUrl(episode.url)} target="_blank" rel="noreferrer" className="home-podcast-item">
                    <MediaPreview kind="audio" image={episode.image} publisher={episode.publisher} title={episode.title} />
                    <span className="min-w-0">
                      <strong className="line-clamp-2">{episode.title}</strong>
                      <small>{episode.publisher}</small>
                      <small className="home-podcast-action">Listen to Episode ↗</small>
                    </span>
                  </a>
                ) : (
                  <div key={episode.id} className="home-podcast-item">
                    <MediaPreview kind="audio" image={episode.image} publisher={episode.publisher} title={episode.title} />
                    <span className="min-w-0">
                      <strong className="line-clamp-2">{episode.title}</strong>
                      <small>{episode.publisher}</small>
                      <small>Episode link unavailable</small>
                    </span>
                  </div>
                )
              ))}
            </div>
          ) : <p className="home-empty">No podcast episodes loaded.</p>}
        </section>

        <section className="home-panel glass">
          <div className="home-section-heading">
            <h2><span aria-hidden="true">◆</span> Trending Now</h2>
          </div>
          {trending.length ? (
            <ol className="home-trending">
              {trending.map((article, index) => (
                <li key={article.id}>
                  <span>{index + 1}</span>
                  <Link href={`/story/${article.id}`} className="home-trending-story" aria-label={article.title}>
                    <ArticleImage article={article} className="home-trending-image" />
                    <span>{article.title}</span>
                  </Link>
                </li>
              ))}
            </ol>
          ) : <p className="home-empty">Trending reports will appear when sources publish updates.</p>}
        </section>
      </div>

      <div className="home-grid-secondary">
        <section className="home-panel glass">
          <div className="home-section-heading"><h2><span aria-hidden="true">⚡</span> Quick Tools</h2></div>
          <div className="home-tools">
            <Link href="/chat"><span>✦</span>Research Desk</Link>
            <Link href="/news"><span>▥</span>Analyse the Story</Link>
            <Link href="/news"><span>✓</span>Fact Check</Link>
            <Link href="/history"><span>◷</span>My Activity</Link>
          </div>
        </section>

        <section className="home-panel glass">
          <div className="home-section-heading">
            <h2><span aria-hidden="true">⌖</span> Regional Updates</h2>
            <Link href="/news?feed=regional">See all →</Link>
          </div>
          {regional.length ? (
            <div className="home-regional">
              {regional.map((article) => (
                <Link key={article.id} href={`/story/${article.id}`} className="home-regional-item">
                  {article.image || article.image_url ? (
                    <img src={article.image || article.image_url} alt="" loading="lazy" />
                  ) : <span className="home-podcast-fallback">MIRA</span>}
                  <span><strong>{article.title}</strong><small>{article.source}</small></span>
                </Link>
              ))}
            </div>
          ) : <p className="home-empty">No regional reports are available.</p>}
        </section>

        <section className="home-explore">
          <div>
            <p className="label">Explore More</p>
            <h2 className="font-display text-2xl font-bold">International coverage</h2>
            <p className="mt-2 text-sm text-white/70">Major global events, crises, and developments affecting the Philippines.</p>
          </div>
          <Link href="/news?feed=international" className="btn !px-5 !py-2 text-sm">Discover →</Link>
        </section>
      </div>
    </div>
  );
}
