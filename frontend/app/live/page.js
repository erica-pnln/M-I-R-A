"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getCachedNews, putCachedNews } from "@/lib/newsCache";
import { getDirectLivePageUrl, getDirectLiveUrl } from "@/lib/media";
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
  "Sports Broadcasters",
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
  const destination = streamUrl || livePageUrl;
  const categories = getLiveCategories(channel);
  const content = (
    <>
      <MediaPreview kind="live" image={channel.image} publisher={channel.publisher} title={channel.title} isLive={channel.is_live === true} />
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
              {streamUrl ? "Verified active broadcast." : "Open the broadcaster’s official live page for current availability."}
            </p>
            <span className="btn mt-3 inline-block !px-4 !py-2 text-xs">
              {streamUrl ? "Watch Live ↗" : "Open Live Page ↗"}
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
    .filter(({ channel, score }) => !search.trim() || (channel.is_live === true && score > 0))
    .sort((left, right) => right.score - left.score)
    .map(({ channel }) => channel);

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      <header className="glass dashboard-hero media-discovery-hero">
        <div><p className="label">Trusted coverage</p><h1 className="font-display text-3xl font-bold">Live News</h1></div>
        <MediaDiscoverySearch
          className="media-discovery-search-hero"
          searchValue={search}
          onSearchChange={setSearch}
          searchLabel="Search live broadcasts"
          placeholder="Search active broadcasts, topics, or channels"
        />
      </header>
      {error && <p role="status" className="rounded-2xl border border-amber-300/20 bg-amber-300/5 px-4 py-3 text-sm text-white/70">{error}</p>}
      {notice && <p className="rounded-2xl border border-blue-300/20 bg-blue-300/5 px-4 py-3 text-sm text-white/70">{notice}</p>}
      <MediaDiscoveryCategories
        categories={LIVE_CATEGORIES}
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
            ? `No active live broadcasts match “${search.trim()}”. Try another keyword or category.`
            : selectedCategory === "All Channels"
              ? "No verified broadcaster channels are available right now."
              : `No broadcaster channels are currently available in ${selectedCategory}.`}
        </p>
      )}
    </div>
  );
}
