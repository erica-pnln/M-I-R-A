"use client";
import { useEffect, useRef, useState } from "react";

const bars = [3, 5, 2, 6, 4, 7, 3, 5, 2, 6, 4, 3];

export default function MediaPreview({ kind, image, publisher, title, isLive = false, className = "" }) {
  const previewRef = useRef(null);
  const [isVisible, setIsVisible] = useState(false);
  const imageUrl = kind === "live" && image
    ? image
      .replace("https://yt3.ggpht.com/", "https://yt3.googleusercontent.com/")
      .replace(/\/maxresdefault\.jpg(?=\?|$)/, "/hqdefault.jpg")
    : image;

  useEffect(() => {
    const preview = previewRef.current;
    if (!preview) return undefined;
    if (!("IntersectionObserver" in window)) {
      setIsVisible(true);
      return undefined;
    }

    const observer = new IntersectionObserver(([entry]) => {
      setIsVisible(entry.isIntersecting);
    }, { rootMargin: "240px" });
    observer.observe(preview);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={previewRef}
      className={`media-preview media-preview-kind-${kind}${isVisible ? " is-visible" : ""}${className ? ` ${className}` : ""}`}
      aria-label={`${kind === "live" ? "Official stream" : "Episode artwork"}: ${title}`}
    >
      {imageUrl && <img className="media-preview-image" src={imageUrl} alt="" loading={isVisible ? "eager" : "lazy"} decoding="async" />}
      <div className="media-preview-shade" aria-hidden="true" />
      {kind === "live" && <span className="media-preview-publisher">{publisher}</span>}
      <span className={kind === "live" ? "media-preview-broadcast" : "media-preview-waveform"} aria-hidden="true">
        {bars.map((height, index) => <i key={index} style={{ "--bar-height": `${height * 4}px` }} />)}
      </span>
      {isLive && <span className="media-preview-live-badge">LIVE</span>}
    </div>
  );
}
