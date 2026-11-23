export function getDirectEpisodeUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    if (
      url.protocol !== "https:"
      || (host !== "podcasts.apple.com" && host !== "itunes.apple.com")
      || !url.pathname.includes("/podcast/")
      || !url.searchParams.get("i")
    ) return "";
    return url.href;
  } catch {
    return "";
  }
}

export function getDirectLiveUrl(value, isLive = false) {
  if (!value) return "";
  try {
    const url = new URL(value);
    const isYoutubeVideo = (
      url.protocol === "https:"
      && (url.hostname === "www.youtube.com" || url.hostname === "youtube.com")
      && url.pathname === "/watch"
      && /^[A-Za-z0-9_-]{11}$/.test(url.searchParams.get("v") || "")
    );
    return isLive && isYoutubeVideo ? url.href : "";
  } catch {
    return "";
  }
}

export function getDirectLivePageUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    const isYoutubeChannelLivePage = (
      url.protocol === "https:"
      && (url.hostname === "www.youtube.com" || url.hostname === "youtube.com")
      && /^\/@?[A-Za-z0-9._-]+\/live\/?$/.test(url.pathname)
    );
    return isYoutubeChannelLivePage ? url.href : "";
  } catch {
    return "";
  }
}

const OFFICIAL_RADIO_SOURCE_HOSTS = new Set([
  "mbc.com.ph",
  "www.dzrh.com.ph",
  "dzrh.com.ph",
  "bomboradyo.com",
  "www.bomboradyo.com",
  "rmn.ph",
  "brigada.ph",
]);

export function getOfficialRadioSourceUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:"
      || url.username
      || url.password
      || !OFFICIAL_RADIO_SOURCE_HOSTS.has(url.hostname.toLowerCase())
    ) return "";
    return url.href;
  } catch {
    return "";
  }
}
