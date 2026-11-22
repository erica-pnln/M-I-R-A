import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import { getCachedArticleImage, putCachedArticleImage } from "@/lib/newsCache";
import { useLanguage } from "@/components/LanguageProvider";

const IMAGE_TIMEOUT_MS = 15000;

export default function ArticleImage({ article, className = "", priority = false }) {
  const { t } = useLanguage();
  const frameRef = useRef(null);
  const [status, setStatus] = useState(article.image ? "loading" : "failed");
  const [imageSrc, setImageSrc] = useState(null);
  const imageUrl = article.image
    ? `${API_BASE}/api/articles/${article.id}/image`
    : null;
  const canLoadPublisherImage = /^https:\/\//i.test(article.image || "");

  useEffect(() => {
    if (status !== "loading" || imageSrc !== article.image || !canLoadPublisherImage) return undefined;
    const timeout = setTimeout(() => setStatus("failed"), IMAGE_TIMEOUT_MS);
    return () => clearTimeout(timeout);
  }, [article.image, canLoadPublisherImage, imageSrc, status]);

  useEffect(() => {
    setStatus(imageUrl ? "loading" : "failed");
    setImageSrc(null);
    if (!imageUrl) return undefined;

    let cancelled = false;
    let objectUrl = null;
    let timeout;
    let observer;
    const controller = new AbortController();

    async function loadImage() {
      try {
        const cachedImage = await getCachedArticleImage(article.id);
        if (cancelled) return;
        if (cachedImage) {
          objectUrl = URL.createObjectURL(cachedImage);
          setImageSrc(objectUrl);
          return;
        }
      } catch (cacheError) {
        console.warn("Could not read a cached MIRA article image:", cacheError);
      }

      if (!navigator.onLine) {
        setStatus("failed");
        return;
      }

      timeout = setTimeout(() => controller.abort(), IMAGE_TIMEOUT_MS);
      try {
        const response = await fetch(imageUrl, {
          signal: controller.signal,
          headers: { Accept: "image/avif,image/webp,image/*,*/*;q=0.8" },
          referrerPolicy: "no-referrer",
        });
        if (!response.ok) throw new Error(`Image request failed (${response.status}).`);
        const blob = await response.blob();
        if (!blob.type.startsWith("image/")) throw new Error("The image endpoint returned an unsupported file.");
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImageSrc(objectUrl);
        putCachedArticleImage(article.id, blob).catch((cacheError) => {
          console.warn("Could not save a cached MIRA article image:", cacheError);
        });
      } catch (imageError) {
        if (cancelled) return;
        if (imageError.name !== "AbortError") {
          console.warn("Could not load a MIRA article image:", imageError);
        }
        if (canLoadPublisherImage) {
          setImageSrc(article.image);
        } else {
          setStatus("failed");
        }
      } finally {
        clearTimeout(timeout);
      }
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
      clearTimeout(timeout);
      observer?.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [article.id, article.image, canLoadPublisherImage, imageUrl, priority]);

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
            onLoad={() => setStatus("loaded")}
            onError={() => setStatus("failed")}
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
