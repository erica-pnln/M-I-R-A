"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getCachedNews, putCachedNews } from "@/lib/newsCache";
import { getDirectEpisodeUrl } from "@/lib/media";
import { getMediaSearchScore, getPodcastCategories } from "@/lib/mediaDiscovery";
import MediaPreview from "@/components/MediaPreview";
import { MediaDiscoveryCategories, MediaDiscoverySearch } from "@/components/MediaDiscoveryControls";

const PODCAST_CATEGORIES = [
  "All Publishers",
  "News Organizations",
  "Independent Creators",
  "Radio Networks",
  "Educational & Campus Media",
  "Government & Institutional Media",
  "International Publishers",
];

function PodcastEpisodeCard({ episode }) {
  const episodeUrl = getDirectEpisodeUrl(episode.url);
  const categories = getPodcastCategories(episode);
  const content = (
    <>
      <MediaPreview kind="audio" image={episode.image} publisher={episode.publisher} title={episode.title} />
      <div className="podcast-card-copy">
        <p className="text-xs font-bold text-mira-blue-light">{episode.publisher}</p>
        <h2 className="mt-1 line-clamp-3 font-display text-lg font-bold">{episode.title}</h2>
        {categories.length > 0 && (
          <div className="media-card-categories">
            {categories.map((category) => <span key={category}>{category}</span>)}
          </div>
        )}
        {episode.description && <p className="mt-2 line-clamp-3 text-xs text-white/60">{episode.description.replace(/<[^>]+>/g, "")}</p>}
        {episode.published && <p className="mt-3 text-xs text-white/45">{new Date(episode.published).toLocaleDateString()}</p>}
        {Number.isFinite(episode.duration) && episode.duration > 0 && (
          <p className="mt-2 text-xs text-white/45">{Math.round(episode.duration / 60000)} min</p>
        )}
        {episodeUrl ? (
          <span className="btn mt-4 inline-block !px-4 !py-2 text-xs">Listen to Episode ↗</span>
        ) : <p className="mt-4 text-xs text-white/50">Episode link unavailable.</p>}
      </div>
    </>
  );

  return episodeUrl ? (
    <a href={episodeUrl} target="_blank" rel="noreferrer" className="podcast-card glass">
      {content}
    </a>
  ) : (
    <article className="podcast-card glass">{content}</article>
  );
}

export default function PodcastPage() {
  const [episodes, setEpisodes] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("All Publishers");

  useEffect(() => {
    let cancelled = false;
    async function loadEpisodes() {
      let cached = null;
      for (const key of ["podcasts:18", "home:podcasts"]) {
        try {
          cached = await getCachedNews(key);
        } catch (cacheError) {
          console.warn(`Could not read cached MIRA podcast episodes (${key}):`, cacheError);
        }
        if (cached) break;
      }
      if (cancelled) return;
      if (cached) {
        setEpisodes(cached.episodes || []);
        setLoading(false);
      }

      if (!navigator.onLine) {
        if (!cached) setError("No locally saved podcast episodes are available offline.");
        setLoading(false);
        return;
      }

      try {
        const result = await api("/api/podcasts?limit=18");
        if (cancelled) return;
        setEpisodes(result.episodes || []);
        putCachedNews("podcasts:18", result).catch((cacheError) => {
          console.warn("Could not save cached MIRA podcast episodes:", cacheError);
        });
      } catch (requestError) {
        if (!cancelled) {
          console.warn("Could not load MIRA podcast episodes:", requestError);
          setError(cached
            ? "Could not refresh podcast episodes. Showing locally saved episodes."
            : "Could not load podcast episodes. Please try again when connected.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadEpisodes();
    return () => { cancelled = true; };
  }, []);

  const filteredEpisodes = episodes
    .filter((episode) => (
      selectedCategory === "All Publishers"
      || getPodcastCategories(episode).includes(selectedCategory)
    ))
    .map((episode) => ({
      episode,
      score: search.trim() ? getMediaSearchScore(episode, search, "podcast") : 1,
    }))
    .filter(({ score }) => !search.trim() || score > 0)
    .sort((left, right) => right.score - left.score)
    .map(({ episode }) => episode);

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      <header className="glass dashboard-hero media-discovery-hero">
        <div><p className="label">Audio journalism</p><h1 className="font-display text-3xl font-bold">Podcasts</h1></div>
        <MediaDiscoverySearch
          className="media-discovery-search-hero"
          searchValue={search}
          onSearchChange={setSearch}
          searchLabel="Search podcast episodes"
          placeholder="Search episode topics, titles, publishers, or genres"
        />
      </header>
      {error && <p role="status" className="rounded-2xl border border-amber-300/20 bg-amber-300/5 px-4 py-3 text-sm text-white/70">{error}</p>}
      <MediaDiscoveryCategories
        categories={PODCAST_CATEGORIES}
        selectedCategory={selectedCategory}
        onSelectCategory={setSelectedCategory}
      />
      {loading ? <p className="home-empty">Loading verified publisher episodes…</p> : filteredEpisodes.length ? (
        <div className="podcast-grid">
          {filteredEpisodes.map((episode) => (
            <PodcastEpisodeCard key={episode.id} episode={episode} />
          ))}
        </div>
      ) : (
        <p className="home-empty" role="status">
          {search.trim()
            ? `No episodes match “${search.trim()}”. Try different keywords or choose All Publishers.`
            : selectedCategory === "All Publishers"
              ? "No publisher episodes are available right now."
              : `No episodes are currently available in ${selectedCategory}.`}
        </p>
      )}
    </div>
  );
}
