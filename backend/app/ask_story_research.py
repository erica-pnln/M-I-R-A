import hashlib
import html
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

import feedparser
import httpx

from . import intelligence, news

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
_SOURCE_CACHE_TTL_SECONDS = 60.0
_SOURCE_CACHE: dict[tuple[str, int], tuple[float, list[dict]]] = {}
_SOURCE_CACHE_LOCK = threading.Lock()
_MAX_SOURCE_BYTES = 3 * 1024 * 1024
_SOURCE_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_REQUESTED_SOURCE_COUNT = re.compile(
    r"\b(?:(?:only|up to|at least|at most|no more than)\s+)?"
    r"(?P<count>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s+(?:relevant\s+|trusted\s+)?(?:sources?|links?)\b",
    re.IGNORECASE,
)
_RESEARCH_REQUEST_NOISE = {
    "about", "article", "at", "can", "comprehensive", "create", "detailed",
    "draft", "explain", "find", "from", "give", "how", "investigate", "least",
    "many", "me", "more", "need", "needed", "news", "of", "only", "please", "related",
    "report", "reports", "research", "source", "sources", "story", "than", "the", "this",
    "to", "up", "what", "with", "write", "evidence", "reference", "references",
    "link", "links", "supporting", "articles",
    *_SOURCE_COUNT_WORDS,
}
_GENERIC_SOURCE_TOPIC_TERMS = {
    "agency", "campaign", "government", "latest", "new", "officials", "report",
    "reports", "role",
}
_BROAD_TOPIC_TERMS = {
    "avenue", "bridge", "car", "cars", "city", "commute", "commuting",
    "congestion", "department", "development", "driving", "expressway",
    "extension", "highway", "highways", "infrastructure", "lane", "lanes",
    "motoring", "motorist", "motorists", "public", "road", "roads", "street",
    "streets", "traffic", "transport", "transportation", "vehicle", "vehicles",
    "works",
}
_TRANSPORT_TOPIC_TERMS = _BROAD_TOPIC_TERMS - {
    "city", "department", "development", "infrastructure", "public", "works",
}
_PHILIPPINE_CONTEXT_TERMS = {
    "caloocan", "cebu", "davao", "dpwh", "iloilo", "luzon", "manila",
    "mindanao", "philippine", "philippines", "visayas",
}
_PHILIPPINE_PUBLISHER_DOMAINS = {
    "bworldonline.com", "gmanetwork.com", "inquirer.net", "manilastandard.net",
    "manilatimes.net", "pna.gov.ph", "pia.gov.ph", "rappler.com",
}
_PUBLISHER_NAME_NOISE = {
    "daily", "media", "network", "news", "online", "philippine", "philippines",
    "the",
}


def requested_source_count(request: str, default: int = 4) -> int:
    match = _REQUESTED_SOURCE_COUNT.search(request)
    if not match:
        return default
    value = match.group("count").casefold()
    count = _SOURCE_COUNT_WORDS.get(value, int(value) if value.isdigit() else default)
    return min(10, max(1, count))


def _relevance_terms(text: str) -> set[str]:
    return {
        token for token in intelligence._tokens(text)
        if token not in _RESEARCH_REQUEST_NOISE and not token.isdigit()
    }


def _publisher_name_tokens(value: str) -> set[str]:
    return {
        token for token in intelligence._tokens(value)
        if token not in _PUBLISHER_NAME_NOISE
    }


def _same_publisher(article: dict, candidate: dict) -> bool:
    article_domain = _trusted_domain(
        str(article.get("url") or article.get("canonical_url") or "")
    )
    candidate_domain = str(candidate.get("domain") or "")
    canonical_domains = {
        "bbc.co.uk": "bbc.com",
    }
    if (
        article_domain
        and candidate_domain
        and canonical_domains.get(article_domain, article_domain)
        == canonical_domains.get(candidate_domain, candidate_domain)
    ):
        return True

    article_name = _publisher_name_tokens(str(article.get("source") or ""))
    candidate_name = _publisher_name_tokens(str(candidate.get("source") or ""))
    return bool(
        article_name
        and candidate_name
        and (article_name <= candidate_name or candidate_name <= article_name)
    )


def _is_relevant_to_story(
    article: dict,
    request: str,
    candidate: dict,
    *,
    require_requested_topics: bool = False,
) -> bool:
    story_text = " ".join(
        str(article.get(key) or "")
        for key in ("title", "summary")
    )
    story_terms = _relevance_terms(f"{story_text} {request}")
    candidate_terms = _relevance_terms(
        " ".join(
            str(candidate.get(key) or "")
            for key in ("title", "summary")
        )
    )
    if not story_terms or not candidate_terms:
        return False

    story_topic_terms = (
        _relevance_terms(story_text)
        - _GENERIC_SOURCE_TOPIC_TERMS
        - _BROAD_TOPIC_TERMS
    )
    candidate_topic_terms = (
        candidate_terms - _GENERIC_SOURCE_TOPIC_TERMS - _BROAD_TOPIC_TERMS
    )
    topic_matches = story_topic_terms & candidate_topic_terms

    if require_requested_topics:
        requested_topics = (
            _relevance_terms(request) - _GENERIC_SOURCE_TOPIC_TERMS
        )
        if requested_topics and not (requested_topics & candidate_terms):
            return False
        return len(topic_matches) >= 2

    if (story_terms - _BROAD_TOPIC_TERMS) & (candidate_terms - _BROAD_TOPIC_TERMS):
        return True

    story_is_philippine = bool(
        story_terms & _PHILIPPINE_CONTEXT_TERMS
        or _trusted_domain(
            str(article.get("url") or article.get("canonical_url") or "")
        ) in _PHILIPPINE_PUBLISHER_DOMAINS
    )
    candidate_is_philippine = (
        str(candidate.get("domain") or "") in _PHILIPPINE_PUBLISHER_DOMAINS
    )
    story_topics = story_terms & _TRANSPORT_TOPIC_TERMS
    candidate_topics = candidate_terms & _TRANSPORT_TOPIC_TERMS
    return bool(
        story_is_philippine
        and candidate_is_philippine
        and story_topics & candidate_topics
    )


def related_sources(
    article: dict,
    request: str,
    candidates: list[dict],
    *,
    limit: int = 4,
    allow_same_publisher: bool = False,
    require_requested_topics: bool = False,
) -> list[dict]:
    """Prefer diverse publishers while optionally filling from repeat publishers."""
    filtered = []
    seen_urls = set()
    for item in candidates:
        candidate = _candidate_from_article(item)
        if (
            not candidate
            or candidate["url"] in seen_urls
            or _same_publisher(article, candidate)
            or not _is_relevant_to_story(
                article,
                request,
                candidate,
                require_requested_topics=require_requested_topics,
            )
        ):
            continue
        filtered.append(item)
        seen_urls.add(candidate["url"])
    distinct_publishers = []
    repeat_publishers = []
    seen_domains = set()
    for item in filtered:
        domain = _candidate_from_article(item)["domain"]
        if domain in seen_domains:
            repeat_publishers.append(item)
        else:
            seen_domains.add(domain)
            distinct_publishers.append(item)
    if allow_same_publisher:
        return (distinct_publishers + repeat_publishers)[:limit]
    return distinct_publishers[:limit]


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
        "at", "least", "many", "more", "need", "needed", "only", "related",
        "source", "sources", "than", "up",
        *_SOURCE_COUNT_WORDS,
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


def _trusted_source_image(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        image_parts = urlsplit(value)
        hostname = image_parts.hostname
    except ValueError:
        return None
    if (
        image_parts.scheme.lower() != "https"
        or not news._trusted_image_host(hostname)
    ):
        return None
    return value


def _candidate_from_article(article: dict) -> dict | None:
    url = article.get("url") or ""
    domain = _trusted_domain(url)
    if not domain:
        return None
    image = _trusted_source_image(article.get("image") or article.get("image_url"))
    summary = _excerpt(article.get("summary"), 900)
    return {
        "title": str(article.get("title") or "").strip(),
        "source": str(article.get("source") or domain).strip(),
        "url": url,
        "image": image,
        "published": article.get("published"),
        "summary": summary,
        "domain": domain,
        "retrieval_origin": article.get("retrieval_origin", "captured"),
    }


def _google_news_candidates(
    query: str,
    limit: int = 16,
    *,
    timeout: float | None = None,
    resolve_timeout: float | None = None,
) -> list[dict]:
    try:
        response = httpx.get(
            "https://news.google.com/rss/search",
            params={
                "q": query,
                "hl": "en-PH",
                "gl": "PH",
                "ceid": "PH:en",
            },
            timeout=timeout or _SEARCH_TIMEOUT_SECONDS,
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
    resolved = (
        news._decode_google_news_urls(urls, timeout=resolve_timeout)
        if resolve_timeout is not None
        else news._decode_google_news_urls(urls)
    )
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
            "image": _feed_image(entry),
            "published": published,
            "summary": _excerpt(entry.get("summary"), 900),
            "domain": domain,
            "retrieval_origin": "external",
        })
    return candidates


def _feed_image(entry: dict) -> str | None:
    for field in ("media_thumbnail", "media_content"):
        media_items = entry.get(field) or []
        if isinstance(media_items, dict):
            media_items = [media_items]
        for item in media_items:
            if not isinstance(item, dict):
                continue
            if image := _trusted_source_image(item.get("url")):
                return image
    return None


def external_sources(query: str, *, limit: int = 5) -> list[dict]:
    """Return a short-lived, relevance-ranked set from one bounded RSS search."""
    cache_key = (query.casefold().strip(), limit)
    now = time.monotonic()
    with _SOURCE_CACHE_LOCK:
        cached = _SOURCE_CACHE.get(cache_key)
        if cached and now - cached[0] < _SOURCE_CACHE_TTL_SECONDS:
            return [dict(source) for source in cached[1]]

    terms = _relevance_terms(query)
    search_queries = [query]
    query_terms = _relevance_terms(query)
    if "philippines" not in query_terms and "philippine" not in query_terms:
        search_queries.append(f"{query} Philippines")
    else:
        search_queries.append(f"{query} reports")
    with ThreadPoolExecutor(max_workers=len(search_queries)) as pool:
        candidates = [
            candidate
            for result in pool.map(
                lambda search_query: _google_news_candidates(
                    search_query,
                    limit=max(24, limit * 5),
                    timeout=1.2,
                    resolve_timeout=1.0,
                ),
                search_queries,
            )
            for candidate in result
        ]
    ranked = []
    required_matches = min(2, len(terms))
    for candidate in candidates:
        title_terms = _relevance_terms(str(candidate.get("title") or ""))
        summary_terms = _relevance_terms(str(candidate.get("summary") or ""))
        matches = terms & (title_terms | summary_terms)
        if not matches or len(matches) < required_matches:
            continue
        ranked.append((
            len(matches) * 3 + len(terms & title_terms) * 2,
            candidate,
        ))

    distinct_publishers = []
    additional_publisher_articles = []
    seen_domains = set()
    seen_urls = set()
    for _score, candidate in sorted(ranked, key=lambda item: item[0], reverse=True):
        url = news._canonical_url(candidate["url"]) or candidate["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        candidate["id"] = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        if candidate["domain"] in seen_domains:
            additional_publisher_articles.append(candidate)
            continue
        seen_domains.add(candidate["domain"])
        distinct_publishers.append(candidate)

    results = (distinct_publishers + additional_publisher_articles)[:limit]

    if len(results) >= limit:
        with _SOURCE_CACHE_LOCK:
            if len(_SOURCE_CACHE) >= 128:
                oldest = min(_SOURCE_CACHE, key=lambda key: _SOURCE_CACHE[key][0])
                _SOURCE_CACHE.pop(oldest, None)
            _SOURCE_CACHE[cache_key] = (
                time.monotonic(),
                [dict(source) for source in results],
            )
    return results


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
    limit: int = 4,
    fetch_article_text: bool = True,
) -> tuple[list[dict], str]:
    candidates: list[dict] = []
    seen_domains: set[str] = set()

    relevant_related = related_sources(
        article,
        request,
        related_articles,
        limit=limit,
        allow_same_publisher=not fetch_article_text,
        require_requested_topics=not fetch_article_text,
    )
    for item in relevant_related:
        candidate = _candidate_from_article(item)
        if not candidate or (
            candidate["domain"] in seen_domains and fetch_article_text
        ):
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

    target_domains = limit
    if not fetch_article_text and len(candidates) < target_domains:
        fallback_query = " ".join(
            sorted(_relevance_terms(f"{title_query} {request}"))
        )
        for candidate in external_sources(
            fallback_query, limit=target_domains - len(candidates)
        ):
            if (
                not any(
                    existing["url"] == candidate["url"]
                    for existing in candidates
                )
                and (
                    not _same_publisher(article, candidate)
                )
                and _is_relevant_to_story(
                    article,
                    request,
                    candidate,
                    require_requested_topics=not fetch_article_text,
                )
            ):
                seen_domains.add(candidate["domain"])
                candidates.append(candidate)
        queries = []
    search_deadline = time.monotonic() + 2.5 if not fetch_article_text else None
    for query in queries:
        if len(seen_domains) >= target_domains:
            break
        remaining = (
            search_deadline - time.monotonic()
            if search_deadline is not None
            else None
        )
        if remaining is not None and remaining <= 0:
            break
        try:
            if remaining is None:
                live_candidates = _google_news_candidates(query)
            else:
                stage_timeout = remaining / 3
                live_candidates = _google_news_candidates(
                    query,
                    timeout=min(_SEARCH_TIMEOUT_SECONDS, stage_timeout),
                    resolve_timeout=stage_timeout,
                )
        except Exception:
            logger.exception("Unexpected Ask Story research-search failure.")
            live_candidates = []
        for candidate in live_candidates:
            if (
                candidate["domain"] in seen_domains
                or _same_publisher(article, candidate)
                or not _is_relevant_to_story(
                    article,
                    request,
                    candidate,
                    require_requested_topics=not fetch_article_text,
                )
            ):
                continue
            seen_domains.add(candidate["domain"])
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    candidates = candidates[:limit]

    if fetch_article_text:
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
    else:
        for candidate in candidates:
            candidate["article_text"] = ""

    candidates.sort(key=lambda candidate: (
        not bool(candidate.get("article_text")),
    ))
    candidates = [
        candidate for candidate in candidates
        if (
            not fetch_article_text
            or candidate.get("article_text")
            or len(candidate.get("summary", "")) >= 60
        )
    ]
    for index, candidate in enumerate(candidates, 1):
        candidate["id"] = f"S{index}"
        candidate["evidence"] = (
            candidate["article_text"]
            or candidate["summary"]
        )

    if len(candidates) >= limit:
        disclosure = (
            f"Research retrieval found {len(candidates)} distinct trusted, relevant "
            "supporting sources. The selected story is not counted."
        )
    else:
        disclosure = (
            f"Research retrieval found only {len(candidates)} distinct trusted, relevant "
            f"supporting sources ({limit} requested). The selected story and unrelated "
            "stories are excluded; disclose this limitation and do not claim that "
            f"{limit} sources were reviewed."
        )
    return candidates, disclosure
