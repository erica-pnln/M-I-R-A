import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import { getCachedArticleImage, putCachedArticleImage } from "@/lib/newsCache";
import { useLanguage } from "@/components/LanguageProvider";

const IMAGE_TIMEOUT_MS = 10000;
const DIRECT_IMAGE_FALLBACK_MS = 5000;

export default function ArticleImage({ article, className = "", priority = false }) {
  const { t } = useLanguage();
  const frameRef = useRef(null);
  const proxyFallbackRef = useRef(null);
  const proxyAttemptedRef = useRef(false);
  const proxyInProgressRef = useRef(false);
  const directFailedRef = useRef(false);
  const imageLoadedRef = useRef(false);
  const [status, setStatus] = useState(article.image ? "loading" : "failed");
  const [imageSrc, setImageSrc] = useState(null);
  const imageUrl = article.image
    ? `${API_BASE}/api/articles/${article.id}/image`
    : null;

  useEffect(() => {
    setStatus(imageUrl ? "loading" : "failed");
    setImageSrc(null);
    proxyAttemptedRef.current = false;
    proxyInProgressRef.current = false;
    directFailedRef.current = false;
    imageLoadedRef.current = false;
    if (!imageUrl) return undefined;

    let cancelled = false;
    let objectUrl = null;
    let proxyTimeout;
    let fallbackTimer;
    let observer;
    const controller = new AbortController();

    async function loadProxyImage(fromDirectError = false) {
      if (proxyAttemptedRef.current) return;
      proxyAttemptedRef.current = true;
      if (!navigator.onLine || (!fromDirectError && imageLoadedRef.current)) {
        if (fromDirectError) setStatus("failed");
        return;
      }

      proxyInProgressRef.current = true;
      proxyTimeout = setTimeout(() => controller.abort(), IMAGE_TIMEOUT_MS);
      try {
        const response = await fetch(imageUrl, {
          signal: controller.signal,
          headers: { Accept: "image/avif,image/webp,image/*,*/*;q=0.8" },
          referrerPolicy: "no-referrer",
        });
        if (!response.ok) throw new Error(`Image request failed (${response.status}).`);
        const blob = await response.blob();
        if (!blob.type.startsWith("image/")) throw new Error("The image endpoint returned an unsupported file.");
        if (cancelled || imageLoadedRef.current && !directFailedRef.current) return;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        objectUrl = URL.createObjectURL(blob);
        setImageSrc(objectUrl);
        putCachedArticleImage(article.id, blob).catch((cacheError) => {
          console.warn("Could not save a cached MIRA article image:", cacheError);
        });
      } catch (imageError) {
        if (cancelled) return;
        if (imageError.name !== "AbortError") {
          console.warn("Could not load a MIRA article image through the image proxy:", imageError);
        }
        if (directFailedRef.current) setStatus("failed");
      } finally {
        clearTimeout(proxyTimeout);
        proxyInProgressRef.current = false;
      }
    }

    proxyFallbackRef.current = loadProxyImage;

    async function loadImage() {
      setImageSrc(article.image || null);
      try {
        const cachedImage = await getCachedArticleImage(article.id);
        if (cancelled) return;
        if (cachedImage && !imageLoadedRef.current) {
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          objectUrl = URL.createObjectURL(cachedImage);
          setImageSrc(objectUrl);
          return;
        }
      } catch (cacheError) {
        console.warn("Could not read a cached MIRA article image:", cacheError);
      }

      if (!navigator.onLine) {
        return;
      }

      fallbackTimer = setTimeout(
        () => loadProxyImage(false),
        DIRECT_IMAGE_FALLBACK_MS,
      );
    }

    if (priority || typeof IntersectionObserver === "undefined" || !frameRef.current) {
      loadImage();
    } else {
      observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          loadImage();
        }
      }, { rootMargin: "400px" });
      observer.observe(frameRef.current);
    }

    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(proxyTimeout);
      clearTimeout(fallbackTimer);
      observer?.disconnect();
      proxyFallbackRef.current = null;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [article.id, article.image, imageUrl, priority]);

  if (imageUrl && status !== "failed") {
    return (
      <div ref={frameRef} className={`article-image-frame ${className}`}>
        {status === "loading" && <span className="article-image-skeleton" aria-hidden="true" />}
        {imageSrc && (
          <img
            src={imageSrc}
            alt={article.title}
            className={`article-image-content${status === "loading" ? " is-loading" : ""}`}
            loading="eager"
            fetchPriority={priority ? "high" : "auto"}
            decoding="async"
            referrerPolicy="no-referrer"
            onLoad={() => {
              imageLoadedRef.current = true;
              setStatus("loaded");
            }}
            onError={() => {
              directFailedRef.current = true;
              if (!proxyAttemptedRef.current) {
                proxyFallbackRef.current?.(true);
              } else if (!proxyInProgressRef.current) {
                setStatus("failed");
              }
            }}
          />
        )}
      </div>
    );
  }

  return (
    <div
      className={`article-image-unavailable ${className}`}
      role="img"
      aria-label={t("No publisher photo available for {title}", { title: article.title })}
    >
      {t("Publisher photo unavailable")}
    </div>
  );
}
