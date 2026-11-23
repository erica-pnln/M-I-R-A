import asyncio
import json
import hashlib
import logging
import os
import re
import threading
import time
from io import BytesIO
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from . import intelligence
from .db import sb
from .feeds import FEEDS, INTEREST_KEYWORDS, NEWS_TOPIC_RULES
from .intelligence import content_recommendations, fast_search, hybrid_search
from .media_sources import classify_news_source, media_search_text
from .search_intelligence import query_with_dates, understand_query

TTL = 600  # fallback refresh interval
_DEFAULT_REFRESH_INTERVALS = {
    "local": 900,
    "regional": 900,
    "national": 600,
    "international": 1200,
}
_cache = {
    "at": 0.0,
    "items": [],
    "stored_loaded": False,
    "last_successful_sync": None,
    "last_successful_sync_by_section": {},
}
_by_id: dict[str, dict] = {}
_refresh_lock = threading.Lock()
_stored_load_lock = threading.Lock()
_refresh_state_lock = threading.Lock()
_image_state_lock = threading.Lock()
_image_enrichment_lock = threading.Lock()
_image_enrichment_pending: dict[str, tuple[dict, bool]] = {}
_image_enrichment_running = False
_refreshing = False
_last_attempt_by_section: dict[str, float] = {}
_image_attempts: dict[str, float] = {}
_generic_image_urls: set[str] = set()
_TAG = re.compile(r"<[^>]+>")
_GOOGLE_IMAGE_SIGNATURE = re.compile(r'data-n-a-sg="([^"]+)"')
_GOOGLE_IMAGE_TIMESTAMP = re.compile(r'data-n-a-ts="([^"]+)"')
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ocid"}
logger = logging.getLogger(__name__)
_SEARCH_CACHE_TTL = 300
_search_cache: dict[tuple, tuple[float, list[dict], list[dict]]] = {}
_search_cache_lock = threading.Lock()
_GENERIC_IMAGE_REUSE_LIMIT = 10
_IMAGE_ENRICHMENT_BATCH_SIZE = 200
_IMAGE_HOST_SUFFIXES = (
    "abs-cbn.com",
    "aljazeera.com",
    "assettype.com",
    "bbci.co.uk",
    "bworldonline.com",
    "cnn.com",
    "da.gov.ph",
    "dbm.gov.ph",
    "dof.gov.ph",
    "dw.com",
    "eeas.europa.eu",
    "espncdn.com",
    "fbcdn.net",
    "france24.com",
    "foxweather.com",
    "gmanews.tv",
    "googleusercontent.com",
    "guim.co.uk",
    "immigration.gov.ph",
    "inquirer.net",
    "irri.org",
    "jamonline.ph",
    "jpost.com",
    "manilastandard.net",
    "manilatimes.net",
    "mediacorp.sg",
    "mindanaotimes.com.ph",
    "mongabay.com",
    "ph",
    "philstar.com",
    "pff.org.ph",
    "pna.gov.ph",
    "ptvnews.ph",
    "rappler.com",
    "thestar.com.my",
    "wixstatic.com",
    "youtube.com",
    "ytimg.com",
)
_EXACT_IMAGE_HOSTS = {
    "ateneo.edu",
    "dzrh-bucket.s3.ap-southeast-1.amazonaws.com",
    "ph.usembassy.gov",
}
_IMAGE_CONTENT_TYPES = {"image/avif", "image/gif", "image/jpeg", "image/png", "image/webp"}
_IMAGE_CONTENT_TYPE_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
}
_IMAGE_FORMAT_CONTENT_TYPES = {
    "AVIF": "image/avif",
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_IMAGE_PIXELS = 40_000_000
_MAX_THUMBNAIL_SIZE = (960, 960)


class _ImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images: list[str] = []
        self.metadata_images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs if value}
        if tag.lower() == "meta":
            property_name = (
                attributes.get("property")
                or attributes.get("name")
                or attributes.get("itemprop")
                or ""
            ).lower()
            if property_name in {"og:image", "og:image:url", "twitter:image", "twitter:image:src", "image"}:
                self.metadata_images.append(attributes.get("content", ""))
        elif tag.lower() == "link":
            rel = (attributes.get("rel") or "").lower().split()
            if "image_src" in rel:
                self.metadata_images.append(attributes.get("href", ""))
        elif tag.lower() in {"img", "source"}:
            image = (
                attributes.get("data-lazy-src")
                or attributes.get("data-original")
                or attributes.get("data-src")
                or ""
            )
            if not image:
                srcset = attributes.get("data-srcset") or attributes.get("srcset") or ""
                image = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
            image = image or attributes.get("src", "")
            if image:
                self.images.append(image)


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG.sub(" ", text or ""))).strip()


def _canonical_url(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return None
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith("utm_")
    ]
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/"),
        urlencode(query),
        "",
    ))


def _usable_image(value: str | None, base_url: str | None = None) -> str | None:
    if not value:
        return None
    image_url = urljoin(base_url or "", value.strip())
    try:
        parts = urlsplit(image_url)
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return None
    if image_url in _generic_image_urls:
        return None
    return image_url


def _trusted_image_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    hostname = hostname.lower().rstrip(".")
    return hostname in _EXACT_IMAGE_HOSTS or any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in _IMAGE_HOST_SUFFIXES
    )


def fetch_article_image(
    image_url: str, *, supports_avif: bool = True, publisher_url: str | None = None
) -> tuple[bytes, str]:
    image_url = _usable_image(image_url)
    if not image_url:
        raise ValueError("Image URL is invalid.")
    parts = urlsplit(image_url)
    if parts.scheme.lower() != "https" or not _trusted_image_host(parts.hostname):
        raise ValueError("Image host is not an approved news publisher or image CDN.")
    if parts.hostname == "pna.gov.ph":
        image_url = urlunsplit((
            parts.scheme,
            "www.pna.gov.ph",
            parts.path,
            parts.query,
            parts.fragment,
        ))
    accept = "image/webp,image/*;q=0.8,*/*;q=0.5"
    if supports_avif:
        accept = f"image/avif,{accept}"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MIRA/0.1; +https://mira.local)",
        "Accept": accept,
    }
    if publisher_url:
        try:
            publisher_parts = urlsplit(publisher_url)
        except ValueError:
            publisher_parts = None
        if (
            publisher_parts
            and publisher_parts.scheme.lower() == "https"
            and _trusted_image_host(publisher_parts.hostname)
        ):
            headers["Referer"] = urlunsplit((
                publisher_parts.scheme,
                publisher_parts.netloc,
                publisher_parts.path,
                "",
                "",
            ))
    current_url = image_url
    for _ in range(6):
        try:
            response = httpx.get(
                current_url,
                timeout=10,
                follow_redirects=False,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            logger.warning("Could not retrieve publisher image %s: %s", current_url, exc)
            raise
        if response.is_redirect:
            redirect_url = urljoin(current_url, response.headers.get("location", ""))
            redirect_parts = urlsplit(redirect_url)
            if (
                redirect_parts.scheme.lower() != "https"
                or not _trusted_image_host(redirect_parts.hostname)
            ):
                raise ValueError("Image redirect points to an unapproved host.")
            current_url = redirect_url
            continue
        response.raise_for_status()
        break
    else:
        raise ValueError("Publisher image exceeded the redirect limit.")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    content_type = _IMAGE_CONTENT_TYPE_ALIASES.get(content_type, content_type)
    if content_type not in _IMAGE_CONTENT_TYPES:
        try:
            with Image.open(BytesIO(response.content)) as source:
                content_type = _IMAGE_FORMAT_CONTENT_TYPES.get(source.format or "")
                source.verify()
        except (UnidentifiedImageError, OSError):
            content_type = None
    if content_type not in _IMAGE_CONTENT_TYPES:
        raise ValueError("Publisher URL did not return a supported image.")
    if len(response.content) > _MAX_IMAGE_BYTES:
        raise ValueError("Publisher image exceeds the maximum allowed size.")
    return response.content, content_type


def optimize_article_image(
    content: bytes, content_type: str, *, supports_webp: bool = True
) -> tuple[bytes, str]:
    if not supports_webp or content_type in {"image/avif", "image/gif"}:
        return content, content_type
    try:
        with Image.open(BytesIO(content)) as source:
            if source.width * source.height > _MAX_IMAGE_PIXELS:
                raise ValueError("Publisher image dimensions exceed the maximum allowed size.")
            image = ImageOps.exif_transpose(source)
            image.thumbnail(_MAX_THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = BytesIO()
            image.save(
                output,
                format="WEBP",
                quality=86,
                method=5,
                icc_profile=source.info.get("icc_profile"),
            )
    except UnidentifiedImageError:
        return content, content_type
    except OSError:
        return content, content_type
    optimized = output.getvalue()
    return (optimized, "image/webp") if len(optimized) < len(content) else (content, content_type)


def _parsed_image(parser: _ImageParser, base_url: str | None = None) -> str | None:
    for value in parser.metadata_images + parser.images:
        image = _usable_image(value, base_url)
        if image:
            return image
    return None


def _google_article_id(article_url: str) -> str | None:
    try:
        parts = urlsplit(article_url)
    except ValueError:
        return None
    path = parts.path.rstrip("/").split("/")
    if (
        parts.hostname != "news.google.com"
        or len(path) < 2
        or path[-2] not in {"articles", "read"}
    ):
        return None
    return path[-1] or None


def _google_article_signature(article_url: str) -> tuple[str, str, str] | None:
    article_id = _google_article_id(article_url)
    if not article_id:
        return None
    query = parse_qs(urlsplit(article_url).query)
    locale = {
        "hl": query.get("hl", ["en-US"])[0],
        "gl": query.get("gl", ["US"])[0],
        "ceid": query.get("ceid", ["US:en"])[0],
    }
    params_url = (
        f"https://news.google.com/rss/articles/{article_id}?"
        f"{urlencode(locale)}"
    )
    response = httpx.get(
        params_url,
        timeout=10,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; MIRA/0.1)"},
    )
    response.raise_for_status()
    signature = _GOOGLE_IMAGE_SIGNATURE.search(response.text)
    timestamp = _GOOGLE_IMAGE_TIMESTAMP.search(response.text)
    if not signature or not timestamp:
        return None
    return article_id, timestamp.group(1), signature.group(1)


def _decode_google_news_urls(article_urls: list[str]) -> dict[str, str]:
    google_urls = [
        url for url in dict.fromkeys(article_urls)
        if _google_article_id(url)
    ]
    if not google_urls:
        return {}

    pending = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_google_article_signature, url): url
            for url in google_urls
        }
        for future in as_completed(futures):
            article_url = futures[future]
            try:
                details = future.result()
            except (httpx.HTTPError, ValueError):
                logger.debug("Could not retrieve Google News article signature for %s", article_url)
                continue
            if details:
                pending.append((article_url, *details))
    if not pending:
        return {}

    context = [
        ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
         None, None, None, None, None, 0, 1],
        "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0,
    ]
    requests_data = []
    for index, (_, article_id, timestamp, signature) in enumerate(pending):
        payload = [
            "garturlreq",
            context,
            article_id,
            int(timestamp) if timestamp.isdigit() else timestamp,
            signature,
        ]
        requests_data.append([
            "Fbv4je",
            json.dumps(payload, separators=(",", ":")),
            None,
            str(index),
        ])

    try:
        response = httpx.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            content="f.req=" + quote(json.dumps([requests_data], separators=(",", ":"))),
            timeout=20,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": "Mozilla/5.0 (compatible; MIRA/0.1)",
            },
        )
        response.raise_for_status()
        body = response.text.split("\n\n", 1)[-1].lstrip()
        if body.startswith(")]}'"):
            body = body.split("\n", 1)[-1].lstrip()
        rows = json.loads(body)
    except (httpx.HTTPError, ValueError, IndexError) as exc:
        logger.warning("Could not resolve Google News article URLs: %s", exc)
        return {}

    decoded_by_index = {}
    ordered = []
    for row in rows:
        if not (isinstance(row, list) and len(row) >= 3 and row[1] == "Fbv4je"):
            continue
        try:
            result = json.loads(row[2]) if isinstance(row[2], str) else row[2]
            if not isinstance(result, list) or len(result) < 2 or result[0] != "garturlres":
                continue
            decoded_url = result[1]
        except (json.JSONDecodeError, TypeError):
            continue
        ordered.append(decoded_url)
        request_id = next((str(value) for value in reversed(row[3:]) if value is not None), None)
        if request_id is not None:
            decoded_by_index[request_id] = decoded_url

    resolved = {}
    for index, (source_url, _, _, _) in enumerate(pending):
        target_url = decoded_by_index.get(str(index))
        if target_url is None and not decoded_by_index and index < len(ordered):
            target_url = ordered[index]
        if target_url and _canonical_url(target_url) and _google_article_id(target_url) is None:
            resolved[source_url] = target_url
    return resolved


def _image(entry: dict, article_url: str | None = None) -> str | None:
    for candidate in entry.get("media_thumbnail", []) + entry.get("media_content", []):
        image = _usable_image(candidate.get("url"), article_url)
        if image:
            return image
    for candidate in entry.get("enclosures", []) + entry.get("links", []):
        if candidate.get("type", "").startswith("image/") or candidate.get("rel") == "enclosure":
            image = _usable_image(candidate.get("href"), article_url)
            if image:
                return image
    fragments = [item.get("value", "") for item in entry.get("content", [])]
    fragments.extend([entry.get("summary", ""), entry.get("description", "")])
    for fragment in fragments:
        parser = _ImageParser()
        try:
            parser.feed(fragment)
        except ValueError:
            continue
        image = _parsed_image(parser, article_url)
        if image:
            return image
    return None


def _article_page_image(article_url: str) -> str | None:
    try:
        response = httpx.get(
            article_url, timeout=8, follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; MIRA/0.1; +https://mira.local)",
                "Accept": "text/html",
            },
        )
        response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("Could not retrieve article image metadata for %s: %s", article_url, exc)
        return None
    content_type = response.headers.get("content-type", "").lower()
    if content_type and "html" not in content_type:
        return None
    parser = _ImageParser()
    try:
        parser.feed(response.text)
    except ValueError:
        return None
    return _parsed_image(parser, str(response.url))


def _page_image(article: dict) -> str | None:
    article_url = article["url"]
    image = _article_page_image(article_url)
    if image or not _google_article_id(article_url):
        return image
    decoded_url = _decode_google_news_urls([article_url]).get(article_url)
    return _article_page_image(decoded_url) if decoded_url else None


def _enrich_missing_images(
    items: list[dict], *, resolve_google_urls: bool = True
) -> None:
    images_by_url = {}
    for article in items:
        image = article.get("image") or article.get("image_url")
        canonical_url = _canonical_url(article.get("url") or "")
        if image and canonical_url:
            images_by_url[canonical_url] = image
    while True:
        now = time.time()
        candidates = []
        with _image_state_lock:
            expired = [
                url for url, attempted_at in _image_attempts.items()
                if now - attempted_at >= 3600
            ]
            for url in expired:
                _image_attempts.pop(url, None)
            for article in items:
                url = article.get("url")
                if article.get("image") or not url or url in _image_attempts:
                    continue
                _image_attempts[url] = now
                candidates.append(article)
                if len(candidates) >= _IMAGE_ENRICHMENT_BATCH_SIZE:
                    break
        if not candidates:
            return

        decoded_urls = (
            _decode_google_news_urls([article["url"] for article in candidates])
            if resolve_google_urls
            else {}
        )
        found = []
        to_fetch = []
        for article in candidates:
            direct_url = decoded_urls.get(article["url"])
            peer_image = images_by_url.get(_canonical_url(direct_url or ""))
            if peer_image:
                article["image"] = peer_image
                found.append({"id": article["id"], "image_url": peer_image})
            else:
                to_fetch.append(article)

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(
                    _page_image,
                    {**article, "url": decoded_urls.get(article["url"], article["url"])},
                ): article
                for article in to_fetch
            }
            for future in as_completed(futures):
                article = futures[future]
                try:
                    image = future.result()
                except Exception:
                    logger.exception("Could not extract article image for %s", article.get("url"))
                    continue
                if image:
                    article["image"] = image
                    found.append({"id": article["id"], "image_url": image})
                    direct_url = decoded_urls.get(article["url"], article["url"])
                    canonical_url = _canonical_url(direct_url)
                    if canonical_url:
                        images_by_url[canonical_url] = image

        if not found:
            continue
        images_by_id = {row["id"]: row["image_url"] for row in found}
        for article in _cache["items"]:
            if article["id"] in images_by_id:
                article["image"] = images_by_id[article["id"]]
                if article.get("image_url") is not None:
                    article["image_url"] = images_by_id[article["id"]]
        if sb is not None:
            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = [
                    pool.submit(
                        sb.table("articles").update({"image_url": row["image_url"]})
                        .eq("id", row["id"]).execute
                    )
                    for row in found
                ]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception:
                        logger.exception("Could not save article image metadata to Supabase")


def _schedule_image_enrichment(
    items: list[dict] | None = None, *, resolve_google_urls: bool = True
) -> None:
    global _image_enrichment_running
    requested_items = _cache["items"] if items is None else items
    with _image_enrichment_lock:
        for article in requested_items:
            if article.get("image") or not article.get("url"):
                continue
            key = str(article.get("id") or article["url"])
            _image_enrichment_pending[key] = (article, resolve_google_urls)
        if _image_enrichment_running or not _image_enrichment_pending:
            return
        _image_enrichment_running = True

    def enrich() -> None:
        global _image_enrichment_running
        while True:
            with _image_enrichment_lock:
                pending = list(_image_enrichment_pending.values())
                _image_enrichment_pending.clear()
                if not pending:
                    _image_enrichment_running = False
                    return
            for should_resolve_google_urls in (True, False):
                batch = [
                    article for article, resolve_urls in pending
                    if resolve_urls is should_resolve_google_urls
                ]
                if not batch:
                    continue
                try:
                    if should_resolve_google_urls:
                        _enrich_missing_images(batch)
                    else:
                        _enrich_missing_images(batch, resolve_google_urls=False)
                except Exception:
                    logger.exception("Background article image enrichment failed")

    threading.Thread(target=enrich, name="mira-image-enrichment", daemon=True).start()


def is_image_enrichment_running() -> bool:
    with _image_enrichment_lock:
        return _image_enrichment_running


async def _pull(client: httpx.AsyncClient, feed: dict) -> tuple[list[dict], str | None]:
    retries = min(3, max(0, int(feed.get("retries", os.getenv("NEWS_REQUEST_RETRIES", "2")))))
    backoff_seconds = max(0.0, float(os.getenv("NEWS_RETRY_BACKOFF_SECONDS", "0.5")))
    parsed = None
    for attempt in range(retries + 1):
        try:
            response = await client.get(feed["url"])
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            break
        except (httpx.HTTPError, ValueError) as exc:
            if attempt >= retries:
                logger.warning("Could not retrieve news feed %s: %s", feed["source"], exc)
                return [], str(exc)
            await asyncio.sleep(backoff_seconds * (2 ** attempt))
    if not parsed or not parsed.entries:
        logger.warning("News feed %s returned no entries", feed["source"])
        return [], "Feed returned no entries"
    items = []
    for e in parsed.entries[:feed.get("max_items", 15)]:
        url = e.get("link")
        canonical_url = _canonical_url(url) if url else None
        if not canonical_url:
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        categories = [tag.get("term", "").strip() for tag in e.get("tags", [])]
        category = next((value for value in categories if value), None)
        source_metadata = e.get("source")
        publisher = (
            source_metadata.get("title")
            if isinstance(source_metadata, dict)
            else None
        ) or feed["source"]
        items.append({
            "id": hashlib.sha1(url.encode()).hexdigest()[:16],
            "title": _clean(e.get("title")),
            "summary": _clean(e.get("summary"))[:500],
            "source": publisher,
            "section": feed["section"],
            "url": url,
            "canonical_url": canonical_url,
            "category": category or feed["section"],
            "image_url": _image(e, url),
            "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", ts) if ts else None,
            "author": _clean(e.get("author")) or None,
        })
    if not items:
        logger.warning("News feed %s had no usable article links", feed["source"])
        return [], "Feed had no usable article links"
    return items, None


async def _pull_feeds(feeds: list[dict]) -> list[tuple[list[dict], str | None]]:
    default_timeout = max(1.0, float(os.getenv("NEWS_REQUEST_TIMEOUT_SECONDS", "10")))
    timeout = min(
        (max(1.0, float(feed.get("timeout_seconds", default_timeout))) for feed in feeds),
        default=default_timeout,
    )
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=8)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        limits=limits,
        headers={"User-Agent": "MIRA/0.1 (research prototype)"},
    ) as client:
        results = await asyncio.gather(
            *(_pull(client, feed) for feed in feeds),
            return_exceptions=True,
        )
    normalized = []
    for feed, result in zip(feeds, results):
        if isinstance(result, Exception):
            logger.error("News feed %s failed unexpectedly: %s", feed["source"], result)
            normalized.append(([], str(result)))
        else:
            normalized.append(result)
    return normalized


def _public_article(article: dict) -> dict:
    summary = _clean(article.get("summary") or "")
    title = article.get("title") or ""
    public_article = {
        "id": article["id"],
        "title": title,
        "summary": summary,
        "source": article["source"],
        "section": article["section"],
        "url": article["url"],
        "category": article.get("category"),
        "topics": _classify_article_topics(title, summary),
        "image": article.get("image_url") or article.get("image"),
        "published": article.get("published"),
        "collected_at": article.get("collected_at"),
        "author": article.get("author"),
    }
    media = classify_news_source(article.get("source"))
    if media:
        public_article["media"] = media
    return public_article


def _normalized_topic_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _normalized_topic_rules() -> dict[str, dict[str, tuple[tuple[str, str], ...]]]:
    return {
        topic: {
            key: tuple(
                (term, f" {_normalized_topic_text(term)} ")
                for term in terms
            )
            for key, terms in rule.items()
        }
        for topic, rule in NEWS_TOPIC_RULES.items()
    }


_NORMALIZED_TOPIC_RULES = _normalized_topic_rules()
_NORMALIZED_TOPIC_RULES_BY_LABEL = {
    topic.casefold(): rule for topic, rule in _NORMALIZED_TOPIC_RULES.items()
}


def _find_topic_hits(
    normalized_text: str,
    terms: tuple[tuple[str, str], ...],
) -> list[tuple[str, int]]:
    return [
        (term, position)
        for term, normalized_term in terms
        if (position := normalized_text.find(normalized_term)) >= 0
    ]


def _score_normalized_news_topic(
    normalized_title: str,
    normalized_summary: str,
    rule: dict[str, tuple[tuple[str, str], ...]],
) -> tuple[float, int]:
    title_anchors = _find_topic_hits(normalized_title, rule["anchors"])
    summary_anchors = _find_topic_hits(normalized_summary, rule["anchors"])
    title_support = _find_topic_hits(normalized_title, rule["support"])
    summary_support = _find_topic_hits(normalized_summary, rule["support"])

    score = 0.0
    if title_anchors:
        first_anchor = min(position for _, position in title_anchors)
        title_length = max(len(normalized_title), 1)
        score += 4.0 + 0.75 * (1 - min(first_anchor / title_length, 1))
        score += min(1.0, 0.45 * (len({term for term, _ in title_anchors}) - 1))
    if summary_anchors:
        score += 1.8 + min(
            0.7,
            0.25 * (len({term for term, _ in summary_anchors}) - 1),
        )
    score += 0.7 * min(len(title_support), 2)
    score += 0.25 * min(len(summary_support), 4)

    title_evidence = title_anchors or title_support
    first_title_evidence = min(
        (position for _, position in title_evidence),
        default=len(normalized_title),
    )
    return score, first_title_evidence


def _matches_news_topic(title: str, summary: str, topic: str) -> bool:
    if topic.casefold() not in _NORMALIZED_TOPIC_RULES_BY_LABEL:
        return False
    return topic.casefold() in {
        label.casefold() for label in _classify_article_topics(title, summary)
    }


def _classify_article_topics(title: str, summary: str) -> list[str]:
    normalized_title = f" {_normalized_topic_text(title)} "
    normalized_summary = f" {_normalized_topic_text(summary)} "
    candidates = []
    for topic, rule in _NORMALIZED_TOPIC_RULES.items():
        score, first_evidence = _score_normalized_news_topic(
            normalized_title,
            normalized_summary,
            rule,
        )
        if score >= 3.0:
            candidates.append((score, -first_evidence, topic))
    if not candidates:
        return []
    _, _, primary_topic = max(candidates, key=lambda item: (item[0], item[1]))
    return [primary_topic]


def _article_matches_topic(article: dict, topic: str) -> bool:
    media = article.get("media") or classify_news_source(article.get("source"))
    if media:
        media_values = {
            str(value).casefold()
            for value in [
                media.get("publisher"),
                media.get("network"),
                media.get("language"),
                media.get("region"),
                media.get("province"),
                media.get("city"),
                *(media.get("categories") or []),
            ]
            if value
        }
        if topic.casefold() in media_values:
            return True

    category = next((label for label in NEWS_TOPIC_RULES if label.casefold() == topic.casefold()), None)
    if category:
        topics = article.get("topics")
        if topics is not None:
            return category.casefold() in {
                value.casefold() for value in topics if isinstance(value, str)
            }
        return _matches_news_topic(
            article.get("title") or "",
            article.get("summary") or "",
            category,
        )

    legacy_topic = next(
        (label for label in INTEREST_KEYWORDS if label.casefold() == topic.casefold()),
        None,
    )
    if legacy_topic is None:
        return False
    text = f'{article.get("title", "")} {article.get("summary", "")}'.casefold()
    return any(keyword.casefold() in text for keyword in INTEREST_KEYWORDS[legacy_topic])


def _publish(items: list[dict], at: float | None = None) -> None:
    image_counts = Counter(
        image
        for article in items
        if (image := article.get("image") or article.get("image_url"))
    )
    generic_images = {
        image for image, count in image_counts.items()
        if count >= _GENERIC_IMAGE_REUSE_LIMIT
    }
    if generic_images:
        _generic_image_urls.update(generic_images)
        for article in items:
            if (article.get("image") or article.get("image_url")) in generic_images:
                article["image"] = None
                if "image_url" in article:
                    article["image_url"] = None
    items.sort(key=lambda article: article.get("published") or "", reverse=True)
    _cache.update(at=at if at is not None else time.time(), items=items)
    _by_id.clear()
    _by_id.update({article["id"]: article for article in items})


def _load_stored_articles() -> list[dict]:
    if sb is None:
        return []
    articles = []
    batch_size = 1000
    for offset in range(0, 100000, batch_size):
        rows = sb.table("articles").select("*").order(
            "published", desc=True
        ).range(offset, offset + batch_size - 1).execute()
        articles.extend(_public_article(row) for row in rows.data)
        if len(rows.data) < batch_size:
            break
    return articles


def _refresh_intervals() -> dict[str, float]:
    configured = json.loads(os.getenv("NEWS_REFRESH_INTERVALS_SECONDS", "{}"))
    if not isinstance(configured, dict):
        raise ValueError("NEWS_REFRESH_INTERVALS_SECONDS must be a JSON object.")
    intervals = dict(_DEFAULT_REFRESH_INTERVALS)
    for section, value in configured.items():
        if section not in intervals:
            raise ValueError(f"Unknown news refresh section: {section}")
        interval = float(value)
        if interval <= 0:
            raise ValueError("News refresh intervals must be positive.")
        intervals[section] = interval
    return intervals


def _due_feeds(section: str | None, force: bool) -> list[dict]:
    now = time.time()
    intervals = _refresh_intervals()
    sections = {section} if section in _DEFAULT_REFRESH_INTERVALS else set(intervals)
    if section == "trending" or section is None:
        sections = set(intervals)
    due_sections = {
        candidate for candidate in sections
        if force or now - _last_attempt_by_section.get(candidate, 0.0)
        >= intervals.get(candidate, TTL)
    }
    return [feed for feed in FEEDS if feed["section"] in due_sections]


def _load_existing_articles(canonical_urls: list[str]) -> dict[str, dict]:
    if sb is None:
        return {}
    existing_rows = {}
    batch_size = 10
    for offset in range(0, len(canonical_urls), batch_size):
        batch = canonical_urls[offset:offset + batch_size]
        response = sb.table("articles").select("id,canonical_url,image_url").in_(
            "canonical_url", batch
        ).execute()
        existing_rows.update({
            row["canonical_url"]: row for row in response.data
        })
    return existing_rows


def _refresh_now(force: bool = False, section: str | None = None) -> list[dict]:
    with _refresh_lock:
        try:
            _load_stored_once()
        except Exception:
            logger.exception("Could not load stored news; continuing with the in-memory cache")

        feeds = _due_feeds(section, force)
        if not feeds:
            return _cache["items"]

        now = time.time()
        for candidate in {feed["section"] for feed in feeds}:
            _last_attempt_by_section[candidate] = now
        results = asyncio.run(_pull_feeds(feeds))
        collected = []
        for feed, result in zip(feeds, results):
            if result[0]:
                collected.extend(result[0])
                synced_at = datetime.now(timezone.utc).isoformat()
                _cache["last_successful_sync"] = synced_at
                _cache["last_successful_sync_by_section"][feed["section"]] = synced_at
        feeds_failed = [
            {"source": feed["source"], "error": result[1]}
            for feed, result in zip(feeds, results)
            if result[1]
        ]
        collected.sort(key=lambda article: article["published"] or "", reverse=True)

        unique_articles = {}
        section_priority = {
            "local": 0,
            "regional": 1,
            "national": 2,
            "international": 3,
        }
        for article in collected:
            existing = unique_articles.get(article["canonical_url"])
            if existing is None:
                unique_articles[article["canonical_url"]] = article
                continue
            if section_priority.get(article.get("section"), 4) < section_priority.get(
                existing.get("section"), 4
            ):
                existing["section"] = article["section"]
            if not existing.get("image_url") and article.get("image_url"):
                existing["image_url"] = article["image_url"]
        collected = list(unique_articles.values())

        items_by_url = {
            _canonical_url(article.get("url") or "") or article.get("url"): article
            for article in _cache["items"]
        }
        items_by_url.update({
            article["canonical_url"]: _public_article(article) for article in collected
        })
        if collected and sb is not None:
            try:
                existing_rows = _load_existing_articles(
                    [article["canonical_url"] for article in collected]
                )
                collected_at = datetime.now(timezone.utc).isoformat()
                for article in collected:
                    stored = existing_rows.get(article["canonical_url"], {})
                    article["id"] = stored.get("id", article["id"])
                    article["collected_at"] = collected_at
                    if not article.get("image_url") and stored.get("image_url"):
                        article["image_url"] = stored["image_url"]
                sb.table("articles").upsert(collected, on_conflict="canonical_url").execute()
                stored_items = _load_stored_articles()
                if stored_items:
                    items_by_url = {
                        _canonical_url(article.get("url") or "") or article.get("url"): article
                        for article in stored_items
                    }
            except Exception:
                logger.exception("Could not update Supabase news; retaining collected articles in memory")
        if collected or not _cache["items"]:
            _publish(list(items_by_url.values()))
        else:
            _cache["at"] = time.time()
        _cache["last_refresh"] = {
            "collected": len(collected),
            "available": len(_cache["items"]),
            "failed_feeds": feeds_failed,
            "last_successful_sync": _cache["last_successful_sync"],
            "last_successful_sync_by_section": dict(
                _cache["last_successful_sync_by_section"]
            ),
        }
        _schedule_image_enrichment()
        return _cache["items"]


def _refresh_in_background(force: bool = True, section: str | None = None) -> None:
    global _refreshing
    try:
        if section is None:
            _refresh_now(force=force)
        else:
            _refresh_now(force=force, section=section)
    except Exception:
        logger.exception("Background news refresh failed")
    finally:
        with _refresh_state_lock:
            _refreshing = False


def start_refresh_background(force: bool = False, section: str | None = None) -> None:
    global _refreshing
    with _refresh_state_lock:
        needs_storage_load = sb is not None and not _cache["items"] and not _cache["stored_loaded"]
        if _refreshing or (not needs_storage_load and not _due_feeds(section, force)):
            return
        _refreshing = True
    threading.Thread(
        target=_refresh_in_background,
        args=(force, section),
        name="mira-news-refresh",
        daemon=True,
    ).start()


def is_refreshing() -> bool:
    with _refresh_state_lock:
        return _refreshing


def refresh(force: bool = False) -> list[dict]:
    return _refresh_now(force=force)


def refresh_status() -> dict:
    return _cache.get("last_refresh") or {
        "collected": 0,
        "available": len(_cache["items"]),
        "failed_feeds": [],
        "last_successful_sync": _cache["last_successful_sync"],
        "last_successful_sync_by_section": dict(
            _cache["last_successful_sync_by_section"]
        ),
    }


def _load_stored_once(force: bool = False) -> None:
    with _stored_load_lock:
        if (_cache["items"] and not force) or sb is None or _cache["stored_loaded"]:
            return
        stored = _load_stored_articles()
        _cache["stored_loaded"] = True
        if stored:
            for article in stored:
                section = article.get("section")
                collected_at = article.get("collected_at")
                if section in _DEFAULT_REFRESH_INTERVALS and collected_at:
                    current = _cache["last_successful_sync_by_section"].get(section)
                    if current is None or collected_at > current:
                        _cache["last_successful_sync_by_section"][section] = collected_at
                    try:
                        collected_epoch = datetime.fromisoformat(
                            collected_at.replace("Z", "+00:00")
                        ).timestamp()
                        _last_attempt_by_section[section] = max(
                            _last_attempt_by_section.get(section, 0.0),
                            collected_epoch,
                        )
                    except ValueError:
                        logger.warning("Ignoring invalid collected_at timestamp for article %s", article.get("id"))
            if _cache["last_successful_sync_by_section"]:
                _cache["last_successful_sync"] = max(
                    _cache["last_successful_sync_by_section"].values()
                )
            if force and _cache["items"]:
                by_url = {
                    _canonical_url(article.get("url") or "") or article.get("url"): article
                    for article in stored
                }
                by_url.update({
                    _canonical_url(article.get("url") or "") or article.get("url"): article
                    for article in _cache["items"]
                })
                _publish(list(by_url.values()), at=0.0)
            else:
                _publish(stored, at=0.0)
            _schedule_image_enrichment()


def ensure_stored_cache_loaded() -> None:
    """Load persisted news before research when the background cache is still cold."""
    _load_stored_once()


def _ensure_cached() -> None:
    if not _cache["items"] and not _cache["stored_loaded"]:
        start_refresh_background()


def list_articles(
    section: str | None,
    q: str | None,
    topic: str | None,
    limit: int = 40,
    interests: list[str] | None = None,
    history: list[dict] | None = None,
    favorites: list[dict] | None = None,
    offset: int = 0,
) -> list[dict]:
    start_refresh_background(section=section)
    items = list(_cache["items"])
    if section and section != "trending":
        items = [a for a in items if a["section"] == section]
    elif section == "trending":
        priority = {"local": 0, "regional": 1, "national": 2, "international": 3}
        items.sort(key=lambda item: item.get("published") or "", reverse=True)
        items.sort(key=lambda item: priority.get(item.get("section"), 4))
    if topic:
        items = [article for article in items if _article_matches_topic(article, topic)]
    if q:
        searchable_items = []
        for article in items:
            media = article.get("media") or classify_news_source(article.get("source")) or {}
            searchable_items.append({**article, "search_metadata": media_search_text(media)})
        items, _ = fast_search(q, searchable_items, limit=limit + offset)
        for article in items:
            article.pop("search_metadata", None)
            article.pop("text", None)
    elif interests or history or favorites:
        items = content_recommendations(
            items, interests, limit=max(limit + offset, 40),
            history=history, favorites=favorites,
        )
    return items[offset:offset + limit]


def count_articles(section: str | None = None, topic: str | None = None) -> int:
    items = _cache["items"]
    if section and section != "trending":
        items = [article for article in items if article.get("section") == section]
    if topic:
        items = [article for article in items if _article_matches_topic(article, topic)]
    return len(items)


def search_discovery(
    query: str,
    *,
    section: str | None = None,
    scope: str = "all",
    topic: str | None = None,
    period: str = "all",
    from_date: date | None = None,
    to_date: date | None = None,
    sort: str = "relevance",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Search the saved archive and query a public news RSS search independently of Trending."""
    if period not in {"all", "latest", "historical"}:
        raise ValueError(f"Unsupported news period: {period}")
    if scope not in {"all", "philippines", "international"}:
        raise ValueError(f"Unsupported news scope: {scope}")
    if sort not in {"relevance", "newest", "oldest"}:
        raise ValueError(f"Unsupported news sort: {sort}")

    intent = understand_query(query, from_date=from_date, to_date=to_date)
    philippines_query = scope == "philippines" or (
        scope == "all"
        and bool(re.search(
            r"\b(?:philippines|philippine|pilipinas|manila|filipino|duterte|eala|"
            r"caraga|mindanao|luzon|visayas|npa)\b",
            intent["query"],
            re.IGNORECASE,
        ))
    )
    rss_query, effective_start, effective_end = query_with_dates(
        intent["query"],
        from_date=intent["from_date"],
        to_date=intent["to_date"],
        period=period,
    )
    cache_key = (
        rss_query.casefold(), section, scope, topic.casefold() if topic else None,
        period, effective_start, effective_end,
    )
    now = time.monotonic()
    with _search_cache_lock:
        cached = _search_cache.get(cache_key)
        if cached and now - cached[0] < _SEARCH_CACHE_TTL:
            candidates, source_errors = cached[1], cached[2]
        else:
            candidates, source_errors = [], []

    if not cached or now - cached[0] >= _SEARCH_CACHE_TTL:
        try:
            _load_stored_once(force=True)
        except Exception:
            logger.exception("Could not load the historical news archive before search")
        candidates = list(_cache["items"])
        archive_exact_match = False
        if (
            candidates
            and section is None
            and scope == "all"
            and topic is None
            and period == "all"
            and intent["from_date"] is None
            and intent["to_date"] is None
            and sort == "relevance"
        ):
            archive_searchable = []
            for article in candidates:
                media = article.get("media") or classify_news_source(article.get("source")) or {}
                archive_searchable.append({
                    **article,
                    "search_metadata": media_search_text(media),
                })
            _, archive_correction = fast_search(
                intent["query"], archive_searchable, limit=1
            )
            exact_matches = intelligence.exact_term_matches(
                archive_correction or intent["query"], archive_searchable
            )
            if exact_matches:
                candidates = exact_matches
                archive_exact_match = True

        feed_section = (
            section if section in {"local", "regional", "national", "international"}
            else "national" if philippines_query else "international"
        )
        locale = ("en-PH", "PH", "PH:en") if feed_section != "international" else ("en-US", "US", "US:en")
        query_url = "https://news.google.com/rss/search?" + urlencode({
            "q": rss_query,
            "hl": locale[0],
            "gl": locale[1],
            "ceid": locale[2],
        })
        feed = {
            "source": "Google News Search",
            "section": feed_section,
            "url": query_url,
            "max_items": 100,
            "timeout_seconds": 5,
            "retries": 0,
        }
        try:
            if archive_exact_match:
                discovered, error = [], None
            else:
                results = asyncio.run(_pull_feeds([feed]))
                discovered, error = results[0]
            if error:
                source_errors = [{"source": feed["source"], "error": error}]
            if discovered:
                collected_at = datetime.now(timezone.utc).isoformat()
                existing = _load_existing_articles([
                    article["canonical_url"] for article in discovered
                ])
                for article in discovered:
                    prior = existing.get(article["canonical_url"], {})
                    article["id"] = prior.get("id", article["id"])
                    article["collected_at"] = collected_at
                    if not article.get("image_url") and prior.get("image_url"):
                        article["image_url"] = prior["image_url"]
                if sb is not None:
                    try:
                        sb.table("articles").upsert(
                            discovered, on_conflict="canonical_url"
                        ).execute()
                    except Exception:
                        logger.exception("Could not archive search-discovered news metadata")
                by_url = {
                    _canonical_url(article.get("url") or "") or article.get("url"): article
                    for article in candidates
                }
                by_url.update({
                    article["canonical_url"]: _public_article(article)
                    for article in discovered
                })
                candidates = list(by_url.values())
                _publish(candidates)
                _cache["stored_loaded"] = True
        except Exception as exc:
            logger.exception("News search source request failed")
            source_errors = [{"source": feed["source"], "error": str(exc)}]
            candidates = list(_cache["items"])

        with _search_cache_lock:
            if len(_search_cache) >= 128:
                oldest_key = min(_search_cache, key=lambda key: _search_cache[key][0])
                _search_cache.pop(oldest_key, None)
            _search_cache[cache_key] = (
                time.monotonic(),
                candidates,
                source_errors,
            )

    filtered = candidates
    if section and section not in {"all", "trending"}:
        filtered = [article for article in filtered if article.get("section") == section]
    if scope == "philippines":
        filtered = [
            article for article in filtered
            if article.get("section") in {"local", "regional", "national"}
        ]
    elif scope == "international":
        filtered = [article for article in filtered if article.get("section") == "international"]
    if topic:
        filtered = [article for article in filtered if _article_matches_topic(article, topic)]
    if period != "all" or effective_start or effective_end:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
        filtered = [
            article for article in filtered
            if (published := _article_date(article)) is not None
            and (effective_start is None or published.date() >= effective_start)
            and (effective_end is None or published.date() <= effective_end)
            and (period != "latest" or published.date() >= cutoff)
            and (period != "historical" or published.date() <= cutoff)
        ]
    searchable = []
    for article in filtered:
        media = article.get("media") or classify_news_source(article.get("source")) or {}
        searchable.append({
            **article,
            "search_metadata": media_search_text(media),
        })
    _, corrected_query = fast_search(
        intent["query"], searchable, limit=1
    )
    ranking_limit = min(len(searchable), max(limit, offset + limit))
    if sort != "relevance" or philippines_query:
        ranking_limit = len(searchable)
    ranked, search_mode = hybrid_search(
        corrected_query or intent["query"],
        searchable,
        limit=ranking_limit,
        use_vector_store=False,
    )
    for article in ranked:
        article.pop("search_metadata", None)
        article.pop("text", None)
    if sort == "newest":
        ranked.sort(key=lambda article: article.get("published") or "", reverse=True)
    elif sort == "oldest":
        ranked.sort(key=lambda article: article.get("published") or "9999", reverse=False)
    elif philippines_query:
        priority = {"local": 0, "regional": 1, "national": 2, "international": 3}
        ranked.sort(key=lambda article: priority.get(article.get("section"), 4))
    total = len(searchable)
    page = ranked[offset:offset + limit]
    missing_images = [
        _by_id[article["id"]]
        for article in page
        if not article.get("image") and article.get("id") in _by_id
    ]
    _schedule_image_enrichment(missing_images, resolve_google_urls=False)
    for article in page:
        updated_article = _by_id.get(article.get("id"))
        if updated_article and updated_article.get("image"):
            article["image"] = updated_article["image"]
    image_enrichment_running = is_image_enrichment_running()
    return {
        "articles": page,
        "total": total,
        "next_offset": offset + limit if offset + limit < total else None,
        "mode": f"archive+live-rss+{search_mode}",
        "corrected_query": corrected_query,
        "corpus_size": len(candidates),
        "source_errors": source_errors,
        "image_enrichment_running": image_enrichment_running,
    }


def _article_date(article: dict) -> datetime | None:
    value = article.get("published")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def get_article(article_id: str, *, enrich_image: bool = True) -> dict | None:
    article = _by_id.get(article_id)
    if article is None:
        if sb is not None:
            try:
                response = sb.table("articles").select("*").eq(
                    "id", article_id
                ).maybe_single().execute()
                if response is None:
                    logger.warning(
                        "Supabase returned no response for article lookup %s",
                        article_id,
                    )
                elif response.data:
                    article = _public_article(response.data)
                    _by_id[article_id] = article
            except Exception:
                logger.exception("Could not retrieve article %s from Supabase", article_id)
        if article is None:
            start_refresh_background()
            return None
    if enrich_image and article and not article.get("image"):
        url = article.get("url")
        if url:
            with _image_state_lock:
                attempted = url in _image_attempts
                if not attempted:
                    _image_attempts[url] = time.time()
            if not attempted:
                image = _page_image(article)
                if image:
                    article["image"] = image
                    if sb is not None:
                        try:
                            sb.table("articles").update({"image_url": image}).eq(
                                "id", article_id
                            ).execute()
                        except Exception:
                            logger.exception(
                                "Could not save article image metadata for %s", article_id
                            )
    return article


def article_text(article: dict) -> str:
    """Best-effort full text for AI context. Falls back to the feed summary."""
    try:
        import trafilatura
        html = trafilatura.fetch_url(article["url"])
        text = trafilatura.extract(html) if html else None
        if text:
            return text[:8000]
    except Exception:
        pass
    return article["summary"]
