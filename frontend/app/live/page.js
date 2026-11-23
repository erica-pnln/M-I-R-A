"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getCachedNews, putCachedNews } from "@/lib/newsCache";
import { getDirectLivePageUrl, getDirectLiveUrl, getOfficialRadioSourceUrl } from "@/lib/media";
import { getLiveCategories, getMediaSearchScore } from "@/lib/mediaDiscovery";
import MediaPreview from "@/components/MediaPreview";
import { MediaDiscoveryCategories, MediaDiscoverySearch } from "@/components/MediaDiscoveryControls";

const LIVE_CATEGORIES = [
  "All Channels",
  "National Broadcasters",
  "Regional & Local Broadcasters",
  "International Broadcasters",
  "Government & Official Channels",
  "Radio Broadcasters",
  "Community Radio Stations",
  "Sports Broadcasters",
  "Television News Broadcasters",
  "Weather & Disaster Coverage",
];

function getOfflineLiveChannels(channels) {
  return channels.map((channel) => {
    const channelImage = channel.channel_image || (channel.is_live === true ? "" : channel.image || "");
    return {
      ...channel,
      url: "",
      image: channelImage,
      channel_image: channelImage,
      is_live: false,
    };
  });
}

function LiveChannelCard({ channel }) {
  const streamUrl = getDirectLiveUrl(channel.url, channel.is_live === true);
  const livePageUrl = getDirectLivePageUrl(channel.live_page_url);
  const sourceUrl = getOfficialRadioSourceUrl(channel.source_page_url);
  const destination = streamUrl || livePageUrl || sourceUrl;
  const categories = getLiveCategories(channel);
  const content = (
    <>
      <MediaPreview kind="live" image={channel.image} logo={channel.logo_url} publisher={channel.publisher} title={channel.title} isLive={channel.is_live === true} />
      <div className="p-4">
        <p className="text-xs font-bold uppercase tracking-wider text-mira-blue-light">{channel.publisher}</p>
        <h3 className="mt-1 font-display text-lg font-bold">{channel.title}</h3>
        {categories.length > 0 && (
          <div className="media-card-categories">
            {categories.map((category) => <span key={category}>{category}</span>)}
          </div>
        )}
        {destination ? (
          <>
            <p className="mt-3 text-xs text-white/50">
              {streamUrl
                ? "Verified active broadcast."
                : livePageUrl
                  ? "Open the broadcaster’s official live page for current availability."
                  : "Official broadcaster source. A live stream may not be available there."}
            </p>
            <span className="btn mt-3 inline-block !px-4 !py-2 text-xs">
              {streamUrl ? "Watch Live ↗" : livePageUrl ? "Open Live Page ↗" : "Visit Official Source ↗"}
            </span>
          </>
        ) : <p className="mt-4 text-xs text-white/50">No direct live page is currently verified.</p>}
      </div>
    </>
  );

  return destination ? (
    <a href={destination} target="_blank" rel="noreferrer" className="live-card live-card-link">
      {content}
    </a>
  ) : (
    <article className="live-card">{content}</article>
  );
}

export default function LivePage() {
  const [channels, setChannels] = useState([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("All Channels");
  const categories = [...new Set([
    ...LIVE_CATEGORIES,
    ...channels.flatMap((channel) => getLiveCategories(channel)),
  ])];

  useEffect(() => {
    let cancelled = false;
    async function loadChannels() {
      let cached = null;
      try {
        cached = await getCachedNews("live:channels");
      } catch (cacheError) {
        console.warn("Could not read cached MIRA live channels:", cacheError);
      }
      if (cancelled) return;
      if (cached) {
        setChannels(getOfflineLiveChannels(cached.channels || []));
        setNotice(cached.notice || "");
        setLoading(false);
      }

      if (!navigator.onLine) {
        if (!cached) setError("No locally saved official channels are available offline.");
        setLoading(false);
        return;
      }

      try {
        const result = await api("/api/live");
        if (cancelled) return;
        setChannels(result.channels || []);
        setNotice(result.notice || "");
        const offlineResult = {
          ...result,
          channels: getOfflineLiveChannels(result.channels || []),
        };
        putCachedNews("live:channels", offlineResult).catch((cacheError) => {
          console.warn("Could not save cached MIRA live channels:", cacheError);
        });
      } catch (requestError) {
        if (!cancelled) {
          console.warn("Could not load MIRA live channels:", requestError);
          setError(cached
            ? "Could not refresh live channels. Showing locally saved channels."
            : "Could not load official channels. Please try again when connected.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadChannels();
    return () => { cancelled = true; };
  }, []);

  const filteredChannels = channels
    .filter((channel) => (
      selectedCategory === "All Channels"
      || getLiveCategories(channel).includes(selectedCategory)
    ))
    .map((channel) => ({
      channel,
      score: search.trim() ? getMediaSearchScore(channel, search, "live") : 1,
    }))
    .filter(({ score }) => !search.trim() || score > 0)
    .sort((left, right) => right.score - left.score)
    .map(({ channel }) => channel);

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      <header className="home-hero home-hero-showcase media-discovery-hero glass">
        {channels[0] && (
          <div
            className="home-hero-backdrop media-discovery-hero-image"
            style={channels[0].image || channels[0].channel_image ? {
              backgroundImage: `linear-gradient(90deg, rgba(0,0,0,.88), rgba(0,0,0,.28)), url("${channels[0].image || channels[0].channel_image}")`,
              backgroundSize: "cover",
              backgroundPosition: "center",
            } : undefined}
            aria-hidden="true"
          />
        )}
        <div className="home-hero-copy">
          <p className="label">Trusted coverage</p>
          <h1 className="font-display">{channels[0]?.title || "Live News"}</h1>
        </div>
        <div className="home-hero-actions">
          <MediaDiscoverySearch
            className="media-discovery-search-hero"
            searchValue={search}
            onSearchChange={setSearch}
            searchLabel="Search live broadcasts"
            placeholder="Search stations, publishers, languages, or locations"
          />
        </div>
      </header>
      {error && <p role="status" className="rounded-2xl border border-amber-300/20 bg-amber-300/5 px-4 py-3 text-sm text-white/70">{error}</p>}
      {notice && <p className="rounded-2xl border border-blue-300/20 bg-blue-300/5 px-4 py-3 text-sm text-white/70">{notice}</p>}
      <MediaDiscoveryCategories
        categories={categories}
        selectedCategory={selectedCategory}
        onSelectCategory={setSelectedCategory}
      />
      {loading ? <p className="home-empty">Loading verified live broadcasts…</p> : filteredChannels.length ? (
        <div className="live-grid">
          {filteredChannels.map((channel) => (
            <LiveChannelCard key={channel.url || `${channel.publisher}-${channel.title}`} channel={channel} />
          ))}
        </div>
      ) : (
        <p className="home-empty" role="status">
          {search.trim()
            ? `No stations or broadcasts match “${search.trim()}”. Try another keyword or category.`
            : selectedCategory === "All Channels"
              ? "No verified broadcaster channels are available right now."
              : `No broadcaster channels are currently available in ${selectedCategory}.`}
        </p>
      )}
    </div>
  );
}
