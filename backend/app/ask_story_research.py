import html
import logging
import os
import re
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
    r"\b(?:(?:only|up to|at most|no more than)\s+)?"
    r"(?P<count>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s+(?:relevant\s+|trusted\s+)?sources?\b",
    re.IGNORECASE,
)
_RESEARCH_REQUEST_NOISE = {
    "about", "article", "at", "can", "comprehensive", "create", "detailed",
    "draft", "explain", "find", "from", "give", "how", "investigate", "least",
    "many", "more", "need", "needed", "news", "of", "only", "please", "related",
    "report", "research", "source", "sources", "story", "than", "the", "this",
    "to", "up", "what", "with", "write",
    *_SOURCE_COUNT_WORDS,
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


def _is_relevant_to_story(article: dict, request: str, candidate: dict) -> bool:
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
) -> list[dict]:
    """Keep distinct, relevant publishers other than the selected story's publisher."""
    filtered = []
    seen_domains = set()
    for item in candidates:
        candidate = _candidate_from_article(item)
        if (
            not candidate
            or candidate["domain"] in seen_domains
            or _same_publisher(article, candidate)
            or not _is_relevant_to_story(article, request, candidate)
        ):
            continue
        seen_domains.add(candidate["domain"])
        filtered.append(item)
        if len(filtered) >= limit:
            break
    return filtered


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
    limit: int = 4,
) -> tuple[list[dict], str]:
    candidates: list[dict] = []
    seen_domains: set[str] = set()

    relevant_related = related_sources(
        article, request, related_articles, limit=limit
    )
    for item in relevant_related:
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

    target_domains = limit
    for query in queries:
        if len(seen_domains) >= target_domains:
            break
        try:
            live_candidates = _google_news_candidates(query)
        except Exception:
            logger.exception("Unexpected Ask Story research-search failure.")
            live_candidates = []
        for candidate in live_candidates:
            if (
                candidate["domain"] in seen_domains
                or _same_publisher(article, candidate)
                or not _is_relevant_to_story(article, request, candidate)
            ):
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
