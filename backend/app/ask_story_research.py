import html
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

import feedparser
import httpx

from . import news

logger = logging.getLogger(__name__)

_TRUSTED_PUBLISHERS = (
    "aljazeera.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "bworldonline.com",
    "cnn.com",
    "dw.com",
    "france24.com",
    "gmanetwork.com",
    "inquirer.net",
    "manilastandard.net",
    "manilatimes.net",
    "npr.org",
    "pna.gov.ph",
    "pia.gov.ph",
    "rappler.com",
    "reuters.com",
    "theguardian.com",
    "un.org",
    "unicef.org",
    "unesco.org",
    "who.int",
    "worldbank.org",
)
_SEARCH_TIMEOUT_SECONDS = max(
    2.0, float(os.getenv("ASK_STORY_SEARCH_TIMEOUT_SECONDS", "8"))
)
_ARTICLE_TIMEOUT_SECONDS = max(
    2.0, float(os.getenv("ASK_STORY_SOURCE_TIMEOUT_SECONDS", "7"))
)
_MAX_SOURCE_BYTES = 3 * 1024 * 1024


def _trusted_domain(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        hostname = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parts.scheme.lower() != "https":
        return None
    for domain in _TRUSTED_PUBLISHERS:
        if hostname == domain or hostname.endswith(f".{domain}"):
            return domain
    if hostname.endswith(".gov") or hostname.endswith(".gov.ph"):
        return hostname
    if hostname.endswith(".edu") or hostname.endswith(".edu.ph"):
        return hostname
    return None


def _excerpt(value: str | None, limit: int = 900) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _search_query(article: dict, request: str) -> str:
    ignored = {
        "article", "comprehensive", "create", "detailed", "draft", "explain",
        "generate", "give", "investigate", "news", "please", "report", "story",
        "write", "about", "this", "that", "with", "from", "what", "how",
    }
    focus = [
        word for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}", request)
        if word.casefold() not in ignored
    ]
    return " ".join(
        [str(article.get("title", "")).strip(), *focus[:10]]
    )[:300].strip()


def _broad_search_query(article: dict) -> str:
    ignored = {
        "about", "after", "also", "and", "are", "buy", "claims", "clarifies",
        "from", "goods", "have", "into", "news", "over", "said", "says",
        "that", "the", "this", "was", "were", "with",
    }
    words = re.findall(r"[A-Za-z][A-Za-z'-]{1,}", str(article.get("title", "")))
    terms = []
    for word in words:
        normalized = "Philippines" if word.casefold() == "ph" else word
        if len(normalized) < 3 and normalized.casefold() != "us":
            continue
        if normalized.casefold() in ignored or normalized.casefold() in {
            term.casefold() for term in terms
        }:
            continue
        terms.append(normalized)
    if len(terms) > 4:
        terms = [*terms[:2], *terms[-2:]]
    return " ".join(terms)


def _candidate_from_article(article: dict) -> dict | None:
    url = article.get("url") or ""
    domain = _trusted_domain(url)
    if not domain:
        return None
    summary = _excerpt(article.get("summary"), 900)
    return {
        "title": str(article.get("title") or "").strip(),
        "source": str(article.get("source") or domain).strip(),
        "url": url,
        "published": article.get("published"),
        "summary": summary,
        "domain": domain,
    }


def _google_news_candidates(query: str, limit: int = 16) -> list[dict]:
    try:
        response = httpx.get(
            "https://news.google.com/rss/search",
            params={
                "q": query,
                "hl": "en-PH",
                "gl": "PH",
                "ceid": "PH:en",
            },
            timeout=_SEARCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "MIRA/0.1 (Ask Story research)"},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Ask Story research search failed: %s", exc)
        return []

    parsed = feedparser.parse(response.content)
    entries = parsed.entries[:limit]
    urls = [entry.get("link", "") for entry in entries if entry.get("link")]
    resolved = news._decode_google_news_urls(urls)
    candidates = []
    for entry in entries:
        wrapped_url = entry.get("link", "")
        url = resolved.get(wrapped_url)
        if not url:
            continue
        domain = _trusted_domain(url)
        if not domain:
            continue
        metadata = entry.get("source")
        publisher = (
            metadata.get("title", "")
            if isinstance(metadata, dict)
            else ""
        ) or domain
        published = entry.get("published")
        candidates.append({
            "title": _excerpt(entry.get("title"), 240),
            "source": _excerpt(publisher, 120),
            "url": url,
            "published": published,
            "summary": _excerpt(entry.get("summary"), 900),
            "domain": domain,
        })
    return candidates


def _fetch_article_text(source: dict) -> str:
    if not _trusted_domain(source.get("url", "")):
        return ""
    try:
        with httpx.stream(
            "GET",
            source["url"],
            timeout=_ARTICLE_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "MIRA/0.1 (Ask Story research)"},
        ) as response:
            response.raise_for_status()
            if not _trusted_domain(str(response.url)):
                logger.info("Skipping untrusted redirected Ask Story source URL.")
                return ""
            content_type = response.headers.get("content-type", "").lower()
            if content_type and "html" not in content_type:
                return ""
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > _MAX_SOURCE_BYTES:
                logger.info("Skipping oversized Ask Story source page.")
                return ""
            chunks = []
            total_bytes = 0
            for chunk in response.iter_bytes():
                total_bytes += len(chunk)
                if total_bytes > _MAX_SOURCE_BYTES:
                    logger.info("Skipping oversized Ask Story source page.")
                    return ""
                chunks.append(chunk)
            page = b"".join(chunks).decode(
                response.encoding or "utf-8", errors="replace"
            )
        import trafilatura
        text = trafilatura.extract(
            page,
            url=str(response.url),
            favor_precision=True,
            include_comments=False,
        )
        return re.sub(r"\s+", " ", text or "").strip()[:2600]
    except (httpx.HTTPError, ValueError, UnicodeError) as exc:
        logger.info("Could not retrieve full text for Ask Story source: %s", exc)
    except Exception:
        logger.exception("Could not extract full text for Ask Story source.")
    return ""


def research_sources(
    article: dict,
    request: str,
    related_articles: list[dict],
    *,
    limit: int = 8,
) -> tuple[list[dict], str]:
    candidates: list[dict] = []
    seen_domains: set[str] = set()

    for item in related_articles:
        candidate = _candidate_from_article(item)
        if not candidate or candidate["domain"] in seen_domains:
            continue
        seen_domains.add(candidate["domain"])
        candidates.append(candidate)

    title_query = str(article.get("title", "")).strip()
    search_query = _search_query(article, request)
    queries = []
    for query in (
        search_query,
        title_query,
        _broad_search_query(article),
    ):
        if query and query.casefold() not in {
            existing.casefold() for existing in queries
        }:
            queries.append(query)

    target_domains = min(5, limit)
    for query in queries:
        if len(seen_domains) >= target_domains:
            break
        try:
            live_candidates = _google_news_candidates(query)
        except Exception:
            logger.exception("Unexpected Ask Story research-search failure.")
            live_candidates = []
        for candidate in live_candidates:
            if candidate["domain"] in seen_domains:
                continue
            seen_domains.add(candidate["domain"])
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    candidates = candidates[:limit]

    with ThreadPoolExecutor(max_workers=min(5, len(candidates) or 1)) as pool:
        futures = {
            pool.submit(_fetch_article_text, candidate): candidate
            for candidate in candidates
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                candidate["article_text"] = future.result()
            except Exception:
                logger.exception(
                    "Ask Story source retrieval task failed for %s.",
                    candidate.get("domain"),
                )
                candidate["article_text"] = ""

    candidates.sort(key=lambda candidate: (
        not bool(candidate.get("article_text")),
    ))
    candidates = [
        candidate for candidate in candidates
        if candidate.get("article_text") or len(candidate.get("summary", "")) >= 60
    ]
    for index, candidate in enumerate(candidates, 1):
        candidate["id"] = f"S{index}"
        candidate["evidence"] = (
            candidate["article_text"]
            or candidate["summary"]
        )

    if len(candidates) >= 5:
        disclosure = (
            f"Research retrieval examined {len(candidates)} distinct trusted "
            "publication domains. It may not include every perspective."
        )
    else:
        disclosure = (
            f"Research retrieval found only {len(candidates)} distinct trusted "
            "publication domains (five requested). Disclose this limitation; "
            "do not claim that five sources were reviewed."
        )
    return candidates, disclosure
