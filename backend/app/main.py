import asyncio
import base64
import binascii
import difflib
import hmac
import json
import logging
import math
import re
import threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePath
from urllib.parse import unquote, urlsplit

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import httpx
from postgrest.exceptions import APIError

from . import ai, ask_story, ask_story_research, intelligence, news
from .auth import optional_user, require_user
from .config import CORS_ORIGINS, NEWS_REFRESH_TOKEN
from .db import sb
from .media_sources import (
    classify_publisher,
    live_channels as radio_live_channels,
    podcast_categories,
)

app = FastAPI(title="MIRA API", version="0.1.0")
logger = logging.getLogger(__name__)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

_TRUSTED_NEWS_DOMAINS = {
    "aljazeera.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "dw.com",
    "france24.com",
    "gmanetwork.com",
    "inquirer.net",
    "pia.gov.ph",
    "pna.gov.ph",
    "rappler.com",
    "reuters.com",
    "theguardian.com",
}
_RESEARCH_CONTEXT_MARKER = re.compile(r"<!--MIRA_RESEARCH:([A-Za-z0-9_-]+)-->")
_RESEARCH_QUERY_NOISE = {
    "about", "affect", "are", "breaking", "can", "could", "current", "find",
    "describe", "explain", "fresh", "freshest", "give", "happen", "happening",
    "help", "important", "last", "latest", "make", "me", "month", "most", "need",
    "new", "newest", "news", "now", "number", "of", "past", "please", "recent",
    "recently", "right", "show", "stories", "story", "tell", "the", "this", "today",
    "top", "trend", "trending", "trends", "want", "week", "what", "whats", "why",
    "with", "would", "year", "yesterday", "you", "at", "least", "many", "more",
    "needed", "related", "topic", "sources", "source", "links", "citations",
    "references", "image", "images", "identify", "analysis", "analyze", "describe",
    "5ws", "1h", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten",
}
_ASSISTANT_TOPIC_NOISE = {
    "answer", "based", "claim", "claims", "current", "database", "evidence",
    "exact", "frame", "image", "news", "note", "provided", "readable", "records",
    "related", "report", "research", "source", "sources", "story", "text",
    "uncertainty", "unverified", "verified", "visible", "visual", "who", "what",
    "when", "where", "why", "how",
}
_SOURCE_LIST_REQUEST = re.compile(
    r"\b(?:sources?|citations?|references?|links?)\b",
    re.IGNORECASE,
)
_RESEARCH_TOPICS = {
    "sports": ("sports", "sport", "basketball", "football", "soccer", "volleyball", "athlete"),
    "politics": ("politics", "political", "government", "election", "senate", "congress"),
    "agriculture": ("agriculture", "agricultural", "farming", "farmers", "rice", "fisheries"),
    "health": ("health", "hospital", "medical", "disease", "outbreak"),
    "environment": ("environment", "climate", "weather", "typhoon", "flood", "storm", "disaster"),
    "business": ("business", "economy", "economic", "trade", "company", "market"),
    "education": ("education", "school", "university", "student", "classroom"),
    "technology": ("technology", "tech", "artificial intelligence", "cybersecurity"),
    "entertainment": ("entertainment", "film", "movie", "music", "celebrity"),
    "crime and safety": ("crime", "police", "safety", "court", "arrest"),
}
_TREND_GENERIC_TITLE_WORDS = {
    "basketball", "game", "games", "league", "nba", "season", "sport", "sports",
    "team", "teams", "win", "wins",
}
_TREND_REQUEST = re.compile(
    r"\btrending?\b|\btop\s+\d+\b|\bmost important\b|\bmost popular\b"
    r"|\bwhat(?:'s| is) happening\b|\b(?:find|show me|list)\b.{0,50}\b"
    r"(?:news|stories|topics)\b",
    re.IGNORECASE,
)
_TREND_ANALYSIS_REQUEST = re.compile(
    r"\b(?:analy[sz]e|analysis|compare|explain|impact|perspectives?|developments?|"
    r"journalism insights?|reporting angles?|unanswered questions?|common findings|"
    r"overview)\b|\bwhy\b.{0,50}\b(?:trending|popular|important)\b|"
    r"\bwhat(?:'s| is) happening\b",
    re.IGNORECASE,
)
_CONTEXTUAL_FOLLOWUP = re.compile(
    r"\b(?:it|its|that|those|them|this issue|this story|this trend|same story|"
    r"number|item|the first|the second|the third|above|follow[- ]?up)\b",
    re.IGNORECASE,
)
_LIVE_RESEARCH_REQUEST = re.compile(
    r"\b(?:latest|current|today|yesterday|recent|news|reported|reporting|"
    r"source|sources|fact[- ]?check|verify|claim|evidence|what happened|"
    r"what(?:'s| is) happening)\b",
    re.IGNORECASE,
)
_NON_RESEARCH_CHAT = {"hello", "hey", "hi", "thanks", "thank", "okay", "ok", "bye"}
_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
    logger.exception("Unhandled API error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.on_event("startup")
def preload_news_cache() -> None:
    try:
        news._ensure_cached()
    except Exception:
        logger.exception("Could not preload the stored news cache")
    news.start_refresh_background()
    threading.Thread(
        target=intelligence.preload_semantic_search,
        name="mira-search-model",
        daemon=True,
    ).start()


class Msg(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    messages: list[Msg]
    conversation_id: str | None = None
    project_id: str | None = None
    mode: str = "auto"


class AskIn(ChatIn):
    article_id: str


class InterestsIn(BaseModel):
    interests: list[str]


class PreferencesIn(BaseModel):
    interests: list[str] | None = None
    news_preferences: list[str] | None = None
    system_language: str | None = None
    language: str | None = None
    ai_language: str | None = None
    journalism_fields: list[str] | None = None
    onboarding_completed: bool | None = None


class SearchHistoryIn(BaseModel):
    query: str


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class ConversationIn(BaseModel):
    project_id: str | None = None


AVAILABLE_JOURNALISM_FIELDS = [
    "Photojournalism",
    "Sports Journalism",
    "Mobile Journalism",
    "Media Arts",
    "Campus Journalism",
    "News Writing",
    "Feature Writing",
    "Editorial Writing",
    "Science and Technology",
    "Investigative Journalism",
    "Campus News Writing",
    "Campus Editorial Writing",
    "Campus Feature Writing",
    "Campus Sports Writing",
    "Campus Science and Technology Writing",
    "Campus Photojournalism",
    "Campus Copyreading and Headline Writing",
    "Campus Cartooning",
    "Campus Radio Broadcasting",
    "Campus TV Broadcasting",
    "Campus Collaborative Publishing",
    "Campus Online Publishing",
]
AVAILABLE_INTERESTS = [
    *AVAILABLE_JOURNALISM_FIELDS,
    "Politics",
    "Health",
    "Sports",
    "Entertainment",
    "Technology",
    "Business",
    "Education",
    "Environment",
    "Agriculture",
    "Crime & Safety",
]
AVAILABLE_LANGUAGES = {"en", "fil", "ceb"}
AI_LANGUAGE_NAMES = {
    "en": "English",
    "fil": "Filipino (Tagalog)",
    "ceb": "Cebuano (Bisaya)",
}


def _save_turn(uid: str | None, conv_id: str | None, kind: str, article: dict | None,
               user_msg: str, reply: str, project_id: str | None = None) -> str | None:
    """Persist a chat turn when the user is signed in and Supabase is configured."""
    if not uid or sb is None:
        return conv_id
    try:
        if not conv_id:
            conversation = {
                "user_id": uid, "kind": kind,
                "article_id": article["id"] if article else None,
                "title": (article["title"] if article else user_msg)[:80],
            }
            if project_id:
                conversation["project_id"] = project_id
            row = sb.table("conversations").insert(conversation).execute()
            conv_id = row.data[0]["id"]
        else:
            existing = sb.table("conversations").select(
                "id,title"
            ).eq("id", conv_id).eq("user_id", uid).maybe_single().execute()
            if not existing.data:
                raise HTTPException(404, "Conversation not found.")
            if existing.data.get("title") == "New chat":
                sb.table("conversations").update({
                    "title": user_msg[:80] or "New chat",
                }).eq("id", conv_id).eq("user_id", uid).execute()
        sb.table("messages").insert([
            {"conversation_id": conv_id, "role": "user", "content": user_msg},
            {"conversation_id": conv_id, "role": "assistant", "content": reply},
        ]).execute()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not save chat messages")
        raise HTTPException(503, "The reply was generated, but chat history could not be saved.") from exc
    return conv_id


def _save_story_turn(
    uid: str | None,
    conv_id: str | None,
    article: dict,
    user_msg: str,
    reply: str,
) -> str | None:
    if not uid:
        return None
    if sb is None:
        raise HTTPException(503, "Supabase is not configured; Ask Story history cannot be saved.")
    try:
        if not conv_id:
            row = sb.table("conversations").insert({
                "user_id": uid,
                "kind": "story",
                "article_id": article["id"],
                "title": article["title"][:80],
            }).execute()
            conv_id = row.data[0]["id"]
        else:
            existing = sb.table("conversations").select(
                "id"
            ).eq("id", conv_id).eq("user_id", uid).eq(
                "kind", "story"
            ).maybe_single().execute()
            if not existing.data:
                raise HTTPException(404, "Ask Story conversation not found.")
        sb.table("messages").insert([
            {"conversation_id": conv_id, "role": "user", "content": user_msg},
            {"conversation_id": conv_id, "role": "assistant", "content": reply},
        ]).execute()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not save Ask Story conversation")
        raise HTTPException(
            503, "The reply was generated, but Ask Story history could not be saved."
        ) from exc
    return conv_id


def _validate_chat_targets(
    uid: str | None, conversation_id: str | None, project_id: str | None,
) -> None:
    if conversation_id is None and project_id is None:
        return
    if not uid or sb is None:
        raise HTTPException(401, "Sign in to save chats in projects or history.")
    if project_id:
        try:
            project = sb.table("projects").select("id").eq(
                "id", project_id
            ).eq("user_id", uid).maybe_single().execute()
        except APIError as exc:
            _require_projects_migration(exc)
            raise
        if not project.data:
            raise HTTPException(404, "Project not found.")
    if conversation_id:
        conversation = sb.table("conversations").select("id").eq(
            "id", conversation_id
        ).eq("user_id", uid).eq("kind", "chat").maybe_single().execute()
        if not conversation.data:
            raise HTTPException(404, "Conversation not found.")


def _chat_system(mode: str, sources: list[dict]) -> str:
    if mode not in ai.CHAT_MODES:
        raise HTTPException(422, "Unsupported MIRA chat mode.")
    system = ai.retrieval_system(sources)
    if ai.CHAT_MODES[mode]:
        system += "\n\n" + ai.CHAT_MODES[mode]
    return system


def _research_chat_system(
    mode: str, sources: list[dict], research: dict,
) -> str:
    system = _chat_system(mode, sources)
    if sources:
        metadata = []
        for index, source in enumerate(sources, 1):
            published = _article_date(source)
            metadata.append(
                f"[S{index}] Category: {source.get('category') or 'unavailable'}; "
                f"Published: {published.date().isoformat() if published else 'unavailable'}; "
                f"Publisher: {source.get('source') or 'unavailable'}"
            )
        system += "\n\nRetrieved record metadata:\n" + "\n".join(metadata)
    system += (
        "\n\nResearch Desk requirements: complete the user's requested journalism task. "
        "For current-news facts, use only the supplied relevant [S#] sources, which may "
        "include fresh news-search results as well as MIRA's stored records. Cite factual "
        "news claims with relevant [S#] citations. "
        "Never invent article counts, engagement metrics, source details, or event facts. "
        "Clearly distinguish reported claims from analysis; label implications and "
        "journalism insights as analysis, not established fact. Answer general-knowledge "
        "and journalism-method questions directly without forcing news citations. Treat "
        "prior assistant replies as topic context only, never as evidence. When the user "
        "asks for sources, list only supplied sources that directly relate to the requested "
        "topic; do not pad with unrelated stories. If fewer relevant sources were retrieved "
        "than requested, state the actual number. If none were retrieved, say that plainly "
        "and offer a focused next step without claiming that no reporting exists."
    )
    if research.get("live_search_failed"):
        system += (
            "\nThe live news search failed. Do not describe stored records as current "
            "or imply that a fresh search succeeded. Disclose this limitation when it "
            "affects the answer."
        )
    if research.get("prefix"):
        system += (
            "\nThe following deterministic trend list is already being shown to the "
            "user. Do not repeat, summarize, or alter it. Do not add general advice, "
            "external research suggestions, or claims unsupported by these records. "
            "If the user explicitly requested analysis, give only a short, clearly "
            "labeled analysis with inline citations. State when the records cannot "
            "establish why a story is trending.\n\n"
            + research["prefix"]
        )
    elif research.get("trend"):
        system += (
            "\nThe user requested an article based on a trend query. Use only the "
            "retrieved MIRA records and their inline citations; do not produce a "
            "separate trend list."
        )
    if mode == "article_generation":
        system += (
            "\nFor an article request, create a clearly structured MIRA AI DRAFT from "
            "the supplied records only, with inline citations, a headline and optional "
            "dek. Do not invent a byline, dateline, quotations, statistics, or facts. "
            "The interface adds a draft publication date and category before the article. "
            "If evidence is insufficient, state what cannot be established rather than "
            "filling gaps."
        )
    return system


def _ai_language_instruction(uid: str | None) -> str:
    language = "en"
    if uid:
        language = _profile_data(uid, "ai_language").get("ai_language") or "en"
    language_name = AI_LANGUAGE_NAMES.get(language, "English")
    style = {
        "en": "Use clear, natural English.",
        "fil": "Use natural, contemporary Filipino (Tagalog), not a stiff word-for-word translation.",
        "ceb": "Use natural Cebuano/Bisaya grammar and expressions, not Filipino or a word-for-word translation.",
    }.get(language, "Use clear, natural English.")
    return (
        f"Respond in {language_name}. {style} Preserve factual accuracy, depth, research quality, "
        "and journalistic standards. Keep proper names, official titles, technical terms, "
        "source titles, URLs, and important quotations accurate; do not translate quoted source "
        "text when the original wording matters. Preserve any required output schema and its "
        "field names, translating only natural-language values."
    )


_ARTICLE_GENERATION_REQUEST = re.compile(
    r"\b(?:write|draft|create|compose|generate|produce|make|prepare)\b.{0,100}\b"
    r"(?:article|news story|news report|feature story|feature article|editorial|op-ed)\b"
    r"|\bturn\b.{0,100}\b(?:into|as)\b.{0,40}\b"
    r"(?:article|news story|news report|feature story|feature article)\b"
    r"|\b(?:i want|i need|please give me|can you give me|could you give me)\b"
    r".{0,60}\b(?:article|news story|news report|feature story|feature article)\b",
    re.IGNORECASE | re.DOTALL,
)


def _requested_chat_mode(mode: str, prompt: str) -> str:
    if re.match(
        r"^\s*(?:how|what|why|when|where|who|explain|describe|teach me|"
        r"tell me|help me understand)\b",
        prompt,
        re.IGNORECASE,
    ):
        return mode
    if mode == "auto" and _ARTICLE_GENERATION_REQUEST.search(prompt):
        return "article_generation"
    return mode


def _chat_task(mode: str, *, has_images: bool = False) -> str:
    if has_images and mode != "article_generation":
        return "image_analysis"
    return {
        "writing_coach": "article_generation",
        "article_generation": "article_generation",
        "media_review": "fact_checking",
    }.get(mode, "general_chat")


def _clean_upload_name(filename: str | None) -> str:
    name = PurePath((filename or "upload").replace("\\", "/")).name
    return re.sub(r"[\x00-\x1f\x7f]", "", name)[:120] or "upload"


def _ai_call(fn, *args):
    try:
        return fn(*args)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {e}")


def _stream_chat_response(
    chunks,
    sources: list[dict],
    uid: str | None,
    conversation_id: str | None,
    kind: str,
    article: dict | None,
    user_message: str,
    project_id: str | None = None,
    uploads_retained: bool | None = None,
    research: dict | None = None,
):
    def event(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def generate():
        response_parts = []
        try:
            prefix = ""
            if research:
                prefix = research.get("article_prefix", "") + research.get("prefix", "")
            if prefix:
                yield event({"type": "token", "text": prefix + "\n\n"})
            for chunk in chunks:
                response_parts.append(chunk)
                yield event({"type": "token", "text": chunk})

            response_text = "".join(response_parts)
            if prefix:
                response_text = f"{prefix}\n\n{response_text}".strip()
            reply = (
                _append_research_source_references(
                    response_text,
                    sources,
                    include_all_sources=bool(
                        research.get("include_all_sources")
                    ),
                )
                if research else ai.append_source_references(
                    response_text, sources, article
                )
            )
            if research:
                reply = _with_research_context(
                    reply,
                    research.get("source_ids", []),
                    research.get("trend_ids", []),
                )
            saved_conversation_id = _save_turn(
                uid,
                conversation_id,
                kind,
                article,
                user_message,
                reply,
                project_id=project_id,
            )
            result: dict[str, object] = {
                "type": "done",
                "reply": reply,
                "conversation_id": saved_conversation_id,
            }
            if uploads_retained is not None:
                result["uploads_retained"] = uploads_retained
            yield event(result)
        except HTTPException as exc:
            logger.exception("Could not complete streaming chat response")
            yield event({"type": "error", "message": str(exc.detail)})
        except Exception as exc:
            logger.exception("AI streaming request failed")
            yield event({"type": "error", "message": f"AI request failed: {exc}"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _intelligence_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except intelligence.IntelligenceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


_IMAGE_QUERY_NOISE = {
    "accurate", "analysis", "analyze", "analyse", "attached", "attachment",
    "check", "describe", "description", "file", "files", "happening", "image",
    "images", "issue", "look", "photo", "photograph", "picture", "pictures",
    "pasted", "please", "show", "source", "sources", "tell", "upload", "uploaded",
    "verify", "verification", "visible", "what",
}


def _image_relevance_filter(
    query: str, articles: list[dict], results: list[dict],
) -> list[dict]:
    query_terms = set(intelligence._tokens(query.replace("-", " "))) - _IMAGE_QUERY_NOISE
    if not query_terms:
        return []

    article_terms = {
        article.get("id"): set(intelligence._tokens(
            f"{article.get('title', '')} {article.get('summary', '')}".replace("-", " ")
        ))
        for article in articles
    }
    frequencies = Counter(
        term for terms in article_terms.values() for term in terms
    )
    rare_terms = {
        term for term in query_terms
        if 0 < frequencies[term] <= max(2, math.ceil(len(articles) * 0.02))
    }
    available_terms = {term for term in query_terms if frequencies[term] > 0}
    anchors = rare_terms or available_terms
    if not anchors or (not rare_terms and len(anchors) < 2):
        return []
    required_matches = min(2, len(anchors))
    return [
        article for article in results
        if (
            len(article_terms.get(article.get("id"), set()) & anchors) >= required_matches
            and bool(
                set(intelligence._tokens(
                    str(article.get("title", "")).replace("-", " ")
                )) & anchors
            )
        )
    ]


def _retrieve(
    query: str,
    exclude_id: str | None = None,
    limit: int = 5,
    strict_image_relevance: bool = False,
) -> list[dict]:
    articles = [
        article
        for article in news.list_articles(None, None, None, limit=1000)
        if article.get("id") != exclude_id and _is_trusted_news_article(article)
    ]
    search_limit = len(articles) if strict_image_relevance else limit
    results, _ = _intelligence_call(
        intelligence.fast_search, query, articles, search_limit
    )
    if strict_image_relevance:
        results = _image_relevance_filter(query, articles, results)[:limit]
    clean_results = []
    for article in results:
        result = dict(article)
        image_url = result.get("image") or result.get("image_url")
        if image_url and not _is_trusted_news_image(image_url):
            result.pop("image", None)
            result.pop("image_url", None)
        clean_results.append(result)
    return clean_results


def _is_contextual_followup(prompt: str) -> bool:
    return bool(_CONTEXTUAL_FOLLOWUP.search(prompt)) or len(
        intelligence._tokens(_research_query(prompt))
    ) <= 1


def _assistant_topic_query(messages: list[dict]) -> str:
    previous_assistant = next(
        (
            str(message.get("content") or "")
            for message in reversed(messages)
            if message.get("role") == "assistant" and message.get("content")
        ),
        "",
    )
    counts = Counter(
        token
        for token in intelligence._tokens(previous_assistant)
        if token not in _ASSISTANT_TOPIC_NOISE and len(token) > 2
    )
    return " ".join(token for token, _count in counts.most_common(8))


def _chat_retrieval_query(messages: list[dict]) -> str:
    prompt = str(messages[-1].get("content") or "")
    query = _research_query(prompt)
    if _is_contextual_followup(prompt):
        previous_user_messages = [
            str(message.get("content") or "")
            for message in messages[-6:-1]
            if message.get("role") == "user" and message.get("content")
        ]
        topic_hint = _assistant_topic_query(messages[:-1])
        context = " ".join((*previous_user_messages[-2:], topic_hint, prompt))
        query = _research_query(context)
    return query


def _rank_chat_sources(
    query: str, articles: list[dict], limit: int = 10,
) -> list[dict]:
    query_tokens = set(intelligence._tokens(query))
    if not query_tokens:
        return []

    candidates = []
    seen = set()
    for article in articles:
        if not _is_trusted_news_article(article):
            continue
        key = str(article.get("id") or article.get("url") or "")
        if key and key not in seen:
            seen.add(key)
            candidates.append(article)
    if not candidates:
        return []

    ranked, corrected_query = _intelligence_call(
        intelligence.fast_search, query, candidates, len(candidates)
    )
    relevant_tokens = set(intelligence._tokens(corrected_query or query))
    minimum_matches = min(2, len(relevant_tokens))
    sources = []
    for article in ranked:
        article_tokens = set(intelligence._tokens(
            f"{article.get('title') or ''} {article.get('summary') or ''}"
        ))
        if len(relevant_tokens & article_tokens) >= minimum_matches:
            sources.append(article)
            if len(sources) >= limit:
                break
    return sources


def _trusted_search_articles(articles: list[dict]) -> list[dict]:
    google_urls = [
        str(article.get("url") or "")
        for article in articles
        if article.get("url")
    ]
    google_urls = [
        url for url in google_urls
        if news._google_article_id(url)
    ][:10]
    decoded_urls = news._decode_google_news_urls(google_urls)
    trusted = []
    for article in articles:
        result = dict(article)
        original_url = str(result.get("url") or "")
        resolved_url = decoded_urls.get(original_url)
        if resolved_url:
            result["url"] = resolved_url
            result["canonical_url"] = news._canonical_url(resolved_url)
        if _is_trusted_news_article(result):
            trusted.append(result)
    return trusted


def _is_trusted_news_article(article: dict) -> bool:
    try:
        parts = urlsplit(article.get("url", ""))
        hostname = (parts.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return False
    return parts.scheme.lower() == "https" and any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in _TRUSTED_NEWS_DOMAINS
    )


def _is_trusted_news_image(image_url: str) -> bool:
    try:
        parts = urlsplit(image_url)
    except (TypeError, ValueError):
        return False
    return (
        parts.scheme.lower() == "https"
        and news._trusted_image_host(parts.hostname)
    )


def _article_date(article: dict) -> datetime | None:
    value = article.get("published")
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _requested_date_window(prompt: str, *, trending: bool) -> tuple[datetime | None, datetime | None]:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    text = prompt.casefold()
    relative = re.search(
        r"\b(?:last|past)\s+(\d{1,2})\s+(hours?|days?|weeks?|months?)\b",
        text,
    )
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).rstrip("s")
        duration = {
            "hour": timedelta(hours=amount),
            "day": timedelta(days=amount),
            "week": timedelta(weeks=amount),
            "month": timedelta(days=30 * amount),
        }[unit]
        return now - duration, None
    if "yesterday" in text:
        return today - timedelta(days=1), today
    if "today" in text:
        return today, None
    if "last week" in text:
        week_start = today - timedelta(days=today.weekday())
        return week_start - timedelta(days=7), week_start
    if "this week" in text:
        return today - timedelta(days=today.weekday()), None
    if "past week" in text or "last 7 days" in text or "past 7 days" in text:
        return now - timedelta(days=7), None
    if "this month" in text or "last 30 days" in text:
        return now - timedelta(days=30), None
    if "this year" in text:
        return now - timedelta(days=365), None
    if trending:
        return now - timedelta(days=14), None
    return None, None


def _research_topic(prompt: str) -> str | None:
    text = prompt.casefold()
    for topic, aliases in _RESEARCH_TOPICS.items():
        if any(
            re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)
            for alias in aliases
        ):
            return topic
    return None


def _research_section(prompt: str) -> str | None:
    text = prompt.casefold()
    for section in ("local", "regional", "national", "international"):
        if re.search(rf"\b{section}\b", text):
            return section
    return None


def _research_query(prompt: str) -> str:
    tokens = intelligence._tokens(prompt.replace("-", " "))
    return " ".join(
        token for token in tokens
        if token not in _RESEARCH_QUERY_NOISE and not token.isdigit()
    )


def _matches_research_filters(
    article: dict,
    *,
    topic: str | None,
    section: str | None,
    philippines_only: bool,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    if section and article.get("section") != section:
        return False
    if philippines_only and article.get("section") not in {"local", "regional", "national"}:
        return False
    if topic:
        aliases = _RESEARCH_TOPICS[topic]
        raw_topics = article.get("topics") or []
        if isinstance(raw_topics, str):
            raw_topics = [raw_topics]
        topic_labels = {
            str(value).casefold() for value in raw_topics
        }
        category = str(article.get("category") or "").casefold()
        text = (
            f" {intelligence._article_text(article)} {category} "
            f"{' '.join(str(value) for value in raw_topics)} "
        ).casefold()
        normalized = f" {re.sub(r'[^a-z0-9]+', ' ', text)} "
        if topic not in topic_labels and not any(
            f" {re.sub(r'[^a-z0-9]+', ' ', alias)} " in normalized
            for alias in aliases
        ):
            return False
    if start or end:
        published = _article_date(article)
        if not published or (start and published < start) or (end and published >= end):
            return False
    return True


def _group_related_articles(articles: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    title_tokens = [
        set(intelligence._tokens(str(article.get("title") or "")))
        for article in articles
    ]
    for article, tokens in zip(articles, title_tokens):
        matching_group = None
        title = str(article.get("title") or "").casefold()
        published = _article_date(article)
        for group in groups:
            representative = group[0]
            representative_tokens = set(
                intelligence._tokens(str(representative.get("title") or ""))
            )
            shared = len(tokens & representative_tokens)
            overlap = shared / max(1, min(len(tokens), len(representative_tokens)))
            similar_title = difflib.SequenceMatcher(
                None, title, str(representative.get("title") or "").casefold()
            ).ratio()
            representative_date = _article_date(representative)
            shared_entities = (
                tokens & representative_tokens
            ) - _TREND_GENERIC_TITLE_WORDS
            same_day_event = bool(
                published
                and representative_date
                and published.date() == representative_date.date()
                and len(shared_entities) >= 3
            )
            if shared >= 2 and (
                overlap >= 0.7 or similar_title >= 0.78 or same_day_event
            ):
                matching_group = group
                break
        if matching_group is None:
            groups.append([article])
        else:
            matching_group.append(article)
    return groups


def _rank_trend_groups(
    groups: list[list[dict]], ranked_ids: list[str], now: datetime | None = None,
) -> list[list[dict]]:
    now = now or datetime.now(timezone.utc)
    rank = {article_id: index for index, article_id in enumerate(ranked_ids)}

    def score(group: list[dict]) -> tuple[float, datetime]:
        dates = [date for article in group if (date := _article_date(article))]
        latest = max(dates, default=datetime.min.replace(tzinfo=timezone.utc))
        age_days = max(0.0, (now - latest).total_seconds() / 86400) if dates else 365.0
        recency = 1 / (1 + age_days / 7)
        coverage = min(len(group), 5) / 5
        relevance = max(
            (1 / (1 + rank.get(str(article.get("id")), len(ranked_ids))) for article in group),
            default=0.0,
        )
        return 0.55 * recency + 0.25 * coverage + 0.2 * relevance, latest

    return sorted(groups, key=score, reverse=True)


def _trend_summary(article: dict) -> str:
    summary = " ".join(str(article.get("summary") or "").split())
    sentences = re.split(r"(?<=[.!?])\s+", summary)
    complete_sentences = [
        sentence for sentence in sentences
        if re.search(r"[.!?][\"'”’)]?$", sentence)
    ]
    preview = " ".join(complete_sentences[:2])
    if len(preview) > 360:
        preview = preview[:357].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return preview


def _format_trend_digest(
    groups: list[list[dict]], sources: list[dict], requested_count: int,
) -> str:
    if not groups:
        return (
            "MIRA’s current news records do not contain enough matching, dated coverage "
            "to identify trends for this request. I can only analyze reports already "
            "available in MIRA."
        )
    source_indexes = {
        str(article["id"]): index for index, article in enumerate(sources, 1)
    }
    lines = [
        "## Current trends in MIRA’s news records",
        "Ranked using publication recency, relevance, and the number of related reports "
        "in MIRA’s collection. Audience-engagement data is not available.",
    ]
    for number, group in enumerate(groups, 1):
        lead = group[0]
        source_id = source_indexes[str(lead["id"])]
        published = _article_date(lead)
        published_text = published.date().isoformat() if published else "Date unavailable in MIRA’s record"
        category = lead.get("category") or lead.get("section") or "Category unavailable"
        summary = _trend_summary(lead)
        lines.extend([
            f"{number}. **{lead.get('title') or 'Untitled report'}** [S{source_id}]",
            f"   Category: {category} · Published: {published_text} · "
            f"Publisher: {lead.get('source') or 'Publisher unavailable'}",
        ])
        if summary:
            lines.append(f"   {summary} [S{source_id}]")
        related_ids = [
            source_indexes[str(article["id"])]
            for article in group[1:]
            if str(article.get("id")) in source_indexes
        ]
        if related_ids:
            related_refs = ", ".join(f"[S{index}]" for index in related_ids)
            lines.append(
                f"   Related coverage: {related_refs} "
                f"({len(group) - 1} related MIRA record"
                f"{'s' if len(group) > 2 else ''})."
            )
    if len(groups) < requested_count:
        lines.append(
            f"MIRA found {len(groups)} matching trend group(s), fewer than the "
            f"{requested_count} requested."
        )
    return "\n\n".join(lines)


def _previous_research_context(messages: list[dict]) -> dict:
    for message in reversed(messages[:-1]):
        if message.get("role") != "assistant":
            continue
        match = _RESEARCH_CONTEXT_MARKER.search(str(message.get("content") or ""))
        if not match:
            continue
        encoded = match.group(1)
        try:
            payload = json.loads(base64.urlsafe_b64decode(
                encoded + "=" * (-len(encoded) % 4)
            ).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, ValueError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        sources = payload.get("sources", [])
        trends = payload.get("trends", [])
        if not isinstance(sources, list) or not isinstance(trends, list):
            return {}
        return {
            "sources": [value for value in sources if isinstance(value, str)],
            "trends": [value for value in trends if isinstance(value, str)],
        }
    return {}


def _numbered_reference(prompt: str) -> int | None:
    match = re.search(r"\b(?:number|no\.?|item|topic|story)\s*#?\s*(\d{1,2})\b|#(\d{1,2})", prompt, re.I)
    if match:
        return int(match.group(1) or match.group(2))
    for word, number in _ORDINAL_WORDS.items():
        if re.search(rf"\b{word}\b", prompt, re.I):
            return number
    return None


def _messages_for_research_model(messages: list[dict]) -> list[dict]:
    cleaned = []
    for index, message in enumerate(messages):
        content = _RESEARCH_CONTEXT_MARKER.sub("", str(message.get("content") or "")).strip()
        if message.get("role") == "assistant" and index < len(messages) - 1:
            content = re.sub(r"\[S\d+\]", "", content)
        cleaned.append({"role": message["role"], "content": content})
    return cleaned


def _with_research_context(reply: str, source_ids: list[str], trend_ids: list[str]) -> str:
    if not source_ids and not trend_ids:
        return reply
    payload = json.dumps(
        {"sources": source_ids, "trends": trend_ids},
        separators=(",", ":"),
    ).encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{reply}\n\n<!--MIRA_RESEARCH:{token}-->"


def _research_article_header(sources: list[dict]) -> str:
    categories = [
        str(source.get("category") or "").strip()
        for source in sources
        if str(source.get("category") or "").strip()
    ]
    category = Counter(categories).most_common(1)[0][0] if categories else "Unclassified"
    category = " ".join(category.split())
    publication_date = datetime.now(timezone.utc).date().isoformat()
    return (
        f"**Category:** {category} · "
        f"**Publication date:** {publication_date} (draft)\n\n"
    )


def _append_research_source_references(
    reply: str,
    sources: list[dict],
    *,
    include_all_sources: bool = False,
) -> str:
    reply = ai.append_source_references(
        reply, sources, include_all_sources=include_all_sources
    )
    for index, source in enumerate(sources, 1):
        published = _article_date(source)
        details = (
            f"  *Category: {source.get('category') or 'Unavailable'} · "
            f"Published: {published.date().isoformat() if published else 'Unavailable'}*\n"
        )
        reply = re.sub(
            rf"(?m)^- \[S{index}\]\n",
            f"- [S{index}]\n{details}",
            reply,
        )
    return reply


def _research_context(messages: list[dict], mode: str) -> dict:
    prompt = messages[-1]["content"]
    source_count = ask_story_research.requested_source_count(prompt)
    previous = _previous_research_context(messages)
    selected_number = _numbered_reference(prompt)
    if selected_number and selected_number <= len(previous.get("trends", [])):
        news.ensure_stored_cache_loaded()
        selected_id = previous["trends"][selected_number - 1]
        article = next(
            (
                article for article in news.list_articles(None, None, None, limit=1000)
                if str(article.get("id")) == selected_id
            ),
            None,
        )
        if article and _is_trusted_news_article(article):
            query = f"{article.get('title', '')} {article.get('summary', '')}"
            related = (
                _retrieve(query, exclude_id=selected_id, limit=source_count - 1)
                if source_count > 1 else []
            )
            sources = [article, *related]
            return {
                "sources": sources,
                "source_ids": [str(item["id"]) for item in sources],
                "trend_ids": previous["trends"],
                "trend": False,
                "prefix": "",
                "insufficient": None,
                "selected_article": article,
            }

    trend = bool(_TREND_REQUEST.search(prompt))
    if trend:
        news.ensure_stored_cache_loaded()
        requested = re.search(r"\btop\s+(\d{1,2})\b", prompt, re.I)
        requested_count = min(10, max(1, int(requested.group(1)))) if requested else 5
        topic = _research_topic(prompt)
        section = _research_section(prompt)
        philippines_only = bool(
            re.search(r"\b(?:philippines|philippine|in the philippines)\b", prompt, re.I)
            and section != "international"
            and section != "national"
        )
        start, end = _requested_date_window(prompt, trending=True)
        candidates = [
            article for article in _retrieve("", limit=1000)
            if _matches_research_filters(
                article,
                topic=topic,
                section=section,
                philippines_only=philippines_only,
                start=start,
                end=end,
            )
        ]
        query = _research_query(prompt)
        if topic:
            category_terms = {
                token
                for alias in _RESEARCH_TOPICS[topic]
                for token in intelligence._tokens(alias)
            }
            query = " ".join(
                token for token in intelligence._tokens(query)
                if token not in category_terms
            )
        query = " ".join(
            token for token in intelligence._tokens(query)
            if token not in {"philippines", "philippine", "national", "international",
                             "local", "regional", "impact"}
        )
        ranked_ids = [str(article["id"]) for article in candidates]
        if query and candidates:
            indexed = [
                {
                    **article,
                    "text": " ".join(str(value or "") for value in (
                        article.get("category"), article.get("section"),
                        " ".join(article.get("topics") or []),
                    )),
                }
                for article in candidates
            ]
            ranked, corrected_query = _intelligence_call(
                intelligence.fast_search, query, indexed, len(indexed)
            )
            ranked_ids = [str(article["id"]) for article in ranked]
            query_tokens = set(intelligence._tokens(corrected_query or query))
            ranked = [
                article for article in ranked
                if query_tokens & set(intelligence._tokens(
                    intelligence._article_text(article)
                ))
            ]
            candidates_by_id = {str(article["id"]): article for article in candidates}
            candidates = [candidates_by_id[str(article["id"])] for article in ranked]
        else:
            candidates.sort(
                key=lambda article: _article_date(article)
                or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
        groups = _rank_trend_groups(_group_related_articles(candidates), ranked_ids)
        groups = groups[:requested_count]
        primary_articles = [group[0] for group in groups]
        sources = list(primary_articles)
        source_ids = [str(article["id"]) for article in sources]
        for group in groups:
            for article in group[1:3]:
                article_id = str(article["id"])
                if article_id not in source_ids and len(sources) < 20:
                    sources.append(article)
                    source_ids.append(article_id)
        trend_ids = [str(article["id"]) for article in primary_articles]
        empty_result = _format_trend_digest([], [], requested_count) if not groups else None
        prefix = empty_result or (
            _format_trend_digest(groups, sources, requested_count)
            if mode != "article_generation"
            else ""
        )
        return {
            "sources": sources,
            "source_ids": source_ids,
            "trend_ids": trend_ids,
            "trend": True,
            "analysis": mode == "article_generation" or bool(
                _TREND_ANALYSIS_REQUEST.search(prompt)
            ),
            "prefix": prefix,
            "insufficient": empty_result,
            "selected_article": None,
        }

    query = _chat_retrieval_query(messages)
    query_tokens = set(intelligence._tokens(query))
    live_search_failed = False
    sources = []
    if query_tokens and not query_tokens.issubset(_NON_RESEARCH_CHAT):
        stored_sources = _rank_chat_sources(
            query, _retrieve(query, limit=20), limit=source_count
        )
        sources = stored_sources
        if _LIVE_RESEARCH_REQUEST.search(prompt):
            discovery = news.search_discovery(
                query, scope="all", period="all", sort="relevance", limit=20,
            )
            live_search_failed = bool(discovery.get("source_errors"))
            discovered = _trusted_search_articles(discovery.get("articles") or [])
            sources = _rank_chat_sources(
                query, [*discovered, *stored_sources], limit=source_count
            )
    if not sources and previous.get("sources") and _is_contextual_followup(prompt):
        articles_by_id = {
            str(article.get("id")): article
            for article in _retrieve("", limit=1000)
        }
        sources = [
            articles_by_id[article_id]
            for article_id in previous["sources"]
            if article_id in articles_by_id
        ][:source_count]
    return {
        "sources": sources,
        "source_ids": [str(article["id"]) for article in sources],
        "trend_ids": [],
        "trend": False,
        "analysis": False,
        "prefix": "",
        "insufficient": None,
        "selected_article": None,
        "live_search_failed": live_search_failed,
        "include_all_sources": bool(_SOURCE_LIST_REQUEST.search(prompt)),
    }


def _upload_retrieval_query(prompt: str, files: list[dict]) -> str:
    query_parts = [prompt]
    for file in files:
        query_parts.append(PurePath(file["name"]).stem.replace("-", " "))
        if file["mime_type"].startswith("text/"):
            query_parts.append(file["data"].decode("utf-8")[:4000])
    return "\n".join(part for part in query_parts if part.strip())


def _upload_retrieval_context(messages: list[dict]) -> str:
    prompts = [
        message["content"]
        for message in messages if message["role"] == "user"
    ]
    if not prompts:
        return ""
    latest = prompts[-1]
    latest_terms = (
        set(intelligence._tokens(latest.replace("-", " "))) - _IMAGE_QUERY_NOISE
    )
    if len(latest_terms) >= 2:
        return latest
    return "\n".join(prompts[-3:])


def _article_keywords(article: dict, text: str) -> list[dict]:
    corpus = [dict(item) for item in news.list_articles(None, None, None, limit=1000)]
    target = next((item for item in corpus if item.get("id") == article["id"]), None)
    if target is None:
        target = dict(article)
        corpus.append(target)
    target["text"] = text
    keywords = _intelligence_call(intelligence.tfidf_keywords, corpus)
    return keywords.get(str(article["id"]), [])


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "supabase": sb is not None,
        "gemini": ai._client is not None,
        "analysis_gemini": ai._analysis_client is not None or ai._client is not None,
        "ai_providers": ai.provider_health(),
    }


def _youtube_channel_artwork(page_html: str, source_url: str) -> str:
    marker = "ytInitialData"
    marker_index = page_html.find(marker)
    if marker_index < 0:
        return ""
    equals_index = page_html.find("=", marker_index + len(marker))
    if equals_index < 0:
        return ""
    try:
        data, _ = json.JSONDecoder().raw_decode(page_html[equals_index + 1:].lstrip())
    except ValueError as exc:
        logger.warning("Could not parse official YouTube channel artwork: %s", exc)
        return ""
    if not isinstance(data, dict):
        return ""

    source_path = urlsplit(source_url).path.rsplit("/live", 1)[0].rstrip("/").casefold()

    def avatar_image(avatar: object) -> str:
        if not isinstance(avatar, dict):
            return ""
        thumbnails = avatar.get("thumbnails")
        if not isinstance(thumbnails, list):
            return ""
        valid_thumbnails = [
            item for item in thumbnails
            if isinstance(item, dict)
            and isinstance(item.get("url"), str)
            and item["url"].startswith("https://")
        ]
        if not valid_thumbnails:
            return ""
        image = max(
            valid_thumbnails,
            key=lambda item: item.get("width", 0)
            if isinstance(item.get("width", 0), int) else 0,
        )["url"]
        host = (urlsplit(image).hostname or "").lower()
        if host not in {"yt3.ggpht.com", "yt3.googleusercontent.com"}:
            return ""
        image = re.sub(r"=s\d+", "=s512", image, count=1)
        return image.replace("https://yt3.ggpht.com/", "https://yt3.googleusercontent.com/", 1)

    exact_matches = []
    metadata_images = {}
    endpoint_images = {}

    def collect_channel_artwork(value: object) -> None:
        if isinstance(value, dict):
            metadata = value.get("channelMetadataRenderer")
            if isinstance(metadata, dict):
                image = avatar_image(metadata.get("avatar"))
                if image:
                    channel_url = metadata.get("vanityChannelUrl") or metadata.get("channelUrl") or ""
                    channel_path = unquote(urlsplit(channel_url).path).casefold()
                    if channel_path == unquote(source_path):
                        exact_matches.append(image)
                    channel_id = metadata.get("externalId") or channel_url
                    metadata_images[channel_id] = image

            endpoint = value.get("channelEndpoint")
            avatar = value.get("channelAvatar")
            if isinstance(endpoint, dict) and isinstance(avatar, dict):
                browse_endpoint = endpoint.get("browseEndpoint")
                canonical_path = (
                    unquote(browse_endpoint.get("canonicalBaseUrl", "")).casefold()
                    if isinstance(browse_endpoint, dict)
                    else ""
                )
                image = avatar_image(avatar)
                if image:
                    endpoint_id = (
                        browse_endpoint.get("browseId") or canonical_path
                        if isinstance(browse_endpoint, dict)
                        else canonical_path
                    )
                    endpoint_images[endpoint_id] = image
                    if canonical_path == unquote(source_path):
                        exact_matches.append(image)
            for child in value.values():
                collect_channel_artwork(child)
        elif isinstance(value, list):
            for child in value:
                collect_channel_artwork(child)

    collect_channel_artwork(data)
    if exact_matches:
        return exact_matches[0]
    if len(metadata_images) == 1:
        return next(iter(metadata_images.values()))
    if len(endpoint_images) == 1:
        return next(iter(endpoint_images.values()))
    return ""


async def _current_youtube_stream(client: httpx.AsyncClient, channel: dict) -> dict | None:
    page_html = ""
    try:
        response = await client.get(channel["source_url"])
        response.raise_for_status()
        page_html = response.text
        marker = "ytInitialPlayerResponse"
        marker_index = page_html.find(marker)
        if marker_index < 0:
            raise ValueError("YouTube player metadata was not present")
        equals_index = page_html.find("=", marker_index + len(marker))
        if equals_index < 0:
            raise ValueError("YouTube player metadata was malformed")
        player, _ = json.JSONDecoder().raw_decode(page_html[equals_index + 1:].lstrip())
        if not isinstance(player, dict):
            raise ValueError("YouTube player metadata was malformed")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not verify current live stream for %s: %s", channel["publisher"], exc)
        image = _youtube_channel_artwork(page_html, channel["source_url"])
        return {"image": image, "channel_image": image} if image else None

    channel_image = _youtube_channel_artwork(page_html, channel["source_url"])
    video = player.get("videoDetails")
    video = video if isinstance(video, dict) else {}
    microformat = player.get("microformat")
    microformat = microformat if isinstance(microformat, dict) else {}
    player_microformat = microformat.get("playerMicroformatRenderer")
    player_microformat = player_microformat if isinstance(player_microformat, dict) else {}
    live_details = player_microformat.get("liveBroadcastDetails")
    live_details = live_details if isinstance(live_details, dict) else {}
    playability = player.get("playabilityStatus")
    playability = playability if isinstance(playability, dict) else {}
    video_id = video.get("videoId")
    if (
        playability.get("status") != "OK"
        or video.get("isLiveContent") is not True
        or live_details.get("isLiveNow") is not True
        or not isinstance(video_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
    ):
        return {"image": channel_image, "channel_image": channel_image} if channel_image else None

    thumbnail = video.get("thumbnail")
    thumbnails = thumbnail.get("thumbnails") if isinstance(thumbnail, dict) else []
    valid_thumbnails = [
        item for item in thumbnails or []
        if isinstance(item, dict)
        and isinstance(item.get("url"), str)
        and item["url"].startswith("https://")
    ]
    small_thumbnails = [
        item for item in valid_thumbnails
        if isinstance(item.get("width"), int) and item["width"] <= 480
    ]
    image_options = small_thumbnails or valid_thumbnails
    image = max(
        image_options,
        key=lambda item: item.get("width", 0)
        if isinstance(item.get("width", 0), int) else 0,
        default={},
    ).get("url", "")
    return {
        "title": video.get("title") or channel["title"],
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "image": image,
        "channel_image": channel_image,
        "stream_description": video.get("shortDescription") or "",
        "tags": video.get("keywords") if isinstance(video.get("keywords"), list) else [],
        "is_live": True,
    }


@app.get("/api/live")
async def live_channels():
    channels = [
        {"category": "Philippine National Live Coverage", "categories": ["National Broadcasters", "Television News Broadcasters"], "description": "Philippine news broadcaster.", "tags": ["ABS-CBN News"], "title": "ABS-CBN News Live", "publisher": "ABS-CBN News", "url": "", "source_url": "https://www.youtube.com/@ABS-CBNNews/live"},
        {"category": "Philippine National Live Coverage", "categories": ["National Broadcasters", "Television News Broadcasters"], "description": "Philippine news broadcaster.", "tags": ["GMA News"], "title": "GMA News Live", "publisher": "GMA News", "url": "", "source_url": "https://www.youtube.com/@gmanews/live"},
        {"category": "Philippine National Live Coverage", "categories": ["National Broadcasters", "Television News Broadcasters"], "description": "Philippine cable news broadcaster.", "tags": ["ANC", "Philippines"], "title": "ANC 24/7 Live", "publisher": "ANC", "url": "", "source_url": "https://www.youtube.com/@ANCALERTS/live"},
        {"category": "Philippine National Live Coverage", "categories": ["Government & Official Channels", "Television News Broadcasters"], "description": "Official Philippine government broadcaster.", "tags": ["People's Television", "Philippines"], "title": "PTV Live", "publisher": "People's Television", "url": "", "source_url": "https://www.youtube.com/PTVphilippines/live"},
        {"category": "Government and Official Public Briefings", "categories": ["Government & Official Channels"], "description": "Official broadcast service for the Office of the President of the Philippines.", "tags": ["RTVM", "Philippines", "public briefings"], "title": "RTVM Live", "publisher": "Radio Television Malacañang", "url": "", "source_url": "https://www.youtube.com/@RTVMalacanang/live"},
        {"category": "Government and Official Public Briefings", "categories": ["Government & Official Channels"], "description": "Official publication of the Government of the Philippines.", "tags": ["Official Gazette", "Philippines"], "title": "Official Gazette", "publisher": "Philippines Official Gazette", "url": ""},
        {"category": "International Live Coverage", "categories": ["International Broadcasters"], "description": "International public-service news broadcaster.", "tags": ["BBC News", "international news"], "title": "BBC News Live", "publisher": "BBC News", "url": "", "source_url": "https://www.youtube.com/@BBCNews/live"},
        {"category": "International Live Coverage", "categories": ["International Broadcasters"], "description": "International news agency and broadcaster.", "tags": ["Reuters", "international news"], "title": "Reuters Live", "publisher": "Reuters", "url": "", "source_url": "https://www.youtube.com/@Reuters/live"},
        {"category": "International Live Coverage", "categories": ["International Broadcasters"], "description": "International news broadcaster.", "tags": ["Al Jazeera English", "international news"], "title": "Al Jazeera English Live", "publisher": "Al Jazeera English", "url": "", "source_url": "https://www.youtube.com/@AlJazeeraEnglish/live"},
    ]
    source_channels = [channel for channel in channels if channel.get("source_url")]
    async with httpx.AsyncClient(
        timeout=12.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"},
    ) as client:
        streams = await asyncio.gather(
            *(_current_youtube_stream(client, channel) for channel in source_channels)
        )
    for channel, stream in zip(source_channels, streams):
        if stream:
            stream_tags = stream.pop("tags", [])
            stream["tags"] = list(dict.fromkeys([*channel.get("tags", []), *stream_tags]))
            channel.update(stream)
        channel["live_page_url"] = channel.pop("source_url", "")
    channels.extend(radio_live_channels())

    return {
        "channels": channels,
        "notice": "A channel is marked LIVE only after its current stream is verified. Verified official live pages are linked when available; radio stations without a verified stream or live page are shown as unavailable.",
    }


@app.get("/api/podcasts")
async def podcasts(
    limit: int = Query(default=12, ge=1, le=30),
):
    terms = [
        "BBC News podcast",
        "Reuters podcast",
        "NPR politics",
        "The Daily New York Times",
        "ABS-CBN News podcast",
        "GMA News podcast",
        "DZRH news podcast",
        "GMA Super Radyo DZBB podcast",
        "RMN Philippines news podcast",
        "Bombo Radyo Philippines news podcast",
        "Aksyon Radyo Philippines news podcast",
        "Brigada News FM podcast",
        "Radyo Pilipinas podcast",
        "Radyo5 True FM podcast",
        "Radyo Veritas podcast",
        "Philippine regional news podcast",
        "Philippine campus journalism podcast",
    ]
    episodes: list[dict] = []
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        async def search_term(term: str) -> tuple[list[dict], set[str]]:
            try:
                response = await client.get(
                    "https://itunes.apple.com/search",
                    params={"term": term, "media": "podcast", "entity": "podcastEpisode", "limit": 2},
                )
                response.raise_for_status()
                term_episodes = []
                unresolved = set()
                for item in response.json().get("results", []):
                    episode_url = item.get("trackViewUrl") or ""
                    if not item.get("trackId") or not episode_url:
                        continue
                    raw_genres = item.get("genres") or []
                    genres = [
                        genre.get("name") if isinstance(genre, dict) else genre
                        for genre in raw_genres
                    ]
                    genres = [genre for genre in genres if isinstance(genre, str)]
                    publisher = item.get("artistName") or ""
                    collection_id = str(item.get("collectionId") or "")
                    show = item.get("collectionName") or ""
                    if collection_id and (not publisher or publisher.casefold() == show.casefold()):
                        unresolved.add(collection_id)
                    episode = {
                        "id": str(item.get("trackId") or item.get("collectionId") or len(episodes)),
                        "title": item.get("trackName") or item.get("collectionName") or "Untitled episode",
                        "publisher": publisher,
                        "show": show,
                        "collection_id": collection_id,
                        "description": item.get("description") or item.get("shortDescription") or "",
                        "genres": genres,
                        "tags": genres,
                        "duration": item.get("trackTimeMillis"),
                        "published": item.get("releaseDate"),
                        "image": item.get("artworkUrl600") or item.get("artworkUrl100"),
                        "url": episode_url,
                    }
                    media = classify_publisher(f"{publisher} {show}")
                    if media:
                        episode["media"] = media
                        episode["categories"] = media["categories"]
                    term_episodes.append(episode)
                return term_episodes, unresolved
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                logger.warning("Could not load podcast search for %s: %s", term, exc)
                return [], set()

        search_results = []
        for start in range(0, len(terms), 5):
            search_results.extend(await asyncio.gather(
                *(search_term(term) for term in terms[start:start + 5])
            ))
        for term_episodes, unresolved in search_results:
            episodes.extend(term_episodes)
        unresolved_collections = set().union(
            *(unresolved for _, unresolved in search_results)
        )

        publisher_lookup_limit = asyncio.Semaphore(5)

        async def lookup_publisher(collection_id: str) -> tuple[str, str]:
            try:
                async with publisher_lookup_limit:
                    response = await client.get(
                        "https://itunes.apple.com/lookup",
                        params={"id": collection_id},
                    )
                response.raise_for_status()
                results = response.json().get("results") or []
                publisher = next(
                    (
                        item.get("artistName")
                        for item in results
                        if isinstance(item, dict) and isinstance(item.get("artistName"), str)
                    ),
                    "",
                )
                return collection_id, publisher
            except (httpx.HTTPError, ValueError) as lookup_error:
                logger.warning("Could not resolve podcast publisher %s: %s", collection_id, lookup_error)
                return collection_id, ""

        publisher_results = await asyncio.gather(
            *(lookup_publisher(collection_id) for collection_id in unresolved_collections)
        )
        publishers_by_collection = dict(publisher_results)
        for episode in episodes:
            lookup_publisher = publishers_by_collection.get(episode["collection_id"])
            if lookup_publisher and (
                not episode["publisher"]
                or episode["publisher"].casefold() == episode["show"].casefold()
            ):
                episode["publisher"] = lookup_publisher
            elif not episode["publisher"]:
                episode["publisher"] = (
                    episode["show"]
                    or "Publisher not listed"
                )
            media = classify_publisher(f'{episode["publisher"]} {episode["show"]}')
            if media:
                episode["media"] = media
            episode["categories"] = podcast_categories(episode)
            episode.pop("collection_id", None)

    unique = []
    seen = set()
    for episode in episodes:
        key = (episode["title"].lower(), episode["publisher"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(episode)
        if len(unique) >= limit:
            break
    return {"episodes": unique}


@app.get("/api/articles")
def articles(
    section: str | None = None,
    q: str | None = None,
    topic: str | None = None,
    uid: str | None = Depends(optional_user),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
):
    interests = []
    if uid and sb is not None:
        profile = _profile_data(uid, "interests")
        interests = profile.get("interests") or []
    try:
        section_count = news.count_articles(section, topic)
        articles = news.list_articles(
            section, q, topic, limit=limit + 1, offset=offset, interests=interests
        )
        has_more = len(articles) > limit
        refresh_status = news.refresh_status() or {}
        return {
            "articles": articles[:limit],
            "total": section_count,
            "next_offset": offset + limit if has_more else None,
            "refreshing": news.is_refreshing(),
            "image_enrichment_running": news.is_image_enrichment_running(),
            "last_successful_sync": refresh_status.get("last_successful_sync"),
        }
    except intelligence.IntelligenceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/dashboard")
def dashboard(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
    uid: str | None = Depends(optional_user),
):
    all_articles = news.list_articles(None, None, None, limit=1000)
    interests: list[str] = []
    history: list[dict] = []
    favorites: list[dict] = []
    searches: list[dict] = []
    language = "en"
    if offset == 0 and uid and sb is not None:
        profile = _profile_data(uid, "interests,system_language,language")
        interests = profile.get("interests") or []
        language = profile.get("system_language") or profile.get("language") or "en"
        history_rows = sb.table("reading_history").select("title,source,url").eq(
            "user_id", uid
        ).order("viewed_at", desc=True).limit(30).execute()
        favorite_rows = sb.table("favorites").select("title,source,url,summary").eq(
            "user_id", uid
        ).order("saved_at", desc=True).limit(30).execute()
        history = history_rows.data or []
        favorites = favorite_rows.data or []
        searches = _optional_rows(
            "search_history",
            lambda query: query.select("query").eq("user_id", uid).order("searched_at", desc=True).limit(30),
        )

    trending = news.list_articles("trending", None, None, limit=limit, offset=offset)
    priority = {"local": 0, "regional": 1, "national": 2, "international": 3}
    trending.sort(key=lambda item: item.get("published") or "", reverse=True)
    trending.sort(key=lambda item: priority.get(item.get("section"), 4))
    trending = trending[:limit]
    recommended = []
    if offset == 0:
        if interests or history or favorites or searches:
            recommended = intelligence.content_recommendations(
                all_articles, interests, limit=min(limit, 40), history=history, favorites=favorites,
                language=language,
            )
    latest = news.list_articles(None, None, None, limit=limit, offset=offset)
    refresh_status = news.refresh_status() or {}
    return {
        "trending": trending,
        "recommended": recommended,
        "latest": latest,
        "has_activity": bool(interests or history or favorites or searches),
        "refreshing": news.is_refreshing(),
        "image_enrichment_running": news.is_image_enrichment_running(),
        "last_successful_sync": refresh_status.get("last_successful_sync"),
        "last_successful_sync_by_section": refresh_status.get("last_successful_sync_by_section", {}),
        "total": news.count_articles(),
        "section_counts": {
            section: news.count_articles(section)
            for section in ("local", "regional", "national", "international")
        },
        "next_offset": offset + len(latest) if offset + len(latest) < news.count_articles() else None,
    }


@app.get("/api/search")
def search_articles(
    q: str = Query(min_length=2),
    section: str | None = None,
    topic: str | None = None,
    scope: str = "all",
    period: str = "all",
    from_date: date | None = None,
    to_date: date | None = None,
    sort: str = "relevance",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
    uid: str | None = Depends(optional_user),
):
    if scope not in {"all", "philippines", "international"}:
        raise HTTPException(422, "Unsupported news coverage filter.")
    if period not in {"all", "latest", "historical"}:
        raise HTTPException(422, "Unsupported news time-period filter.")
    if sort not in {"relevance", "newest", "oldest"}:
        raise HTTPException(422, "Unsupported news sort order.")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(422, "The start date must be on or before the end date.")
    if uid and sb is not None:
        def record_search() -> None:
            try:
                sb.table("search_history").insert(
                    {"user_id": uid, "query": q.strip()}
                ).execute()
            except Exception:
                logger.exception("Could not save search history")
        threading.Thread(target=record_search, name="mira-search-history", daemon=True).start()
    return _intelligence_call(
        news.search_discovery,
        q,
        section=section,
        scope=scope,
        topic=topic,
        period=period,
        from_date=from_date,
        to_date=to_date,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@app.get("/api/topics")
def topics(limit: int = Query(default=250, ge=2, le=1000),
           topic_count: int = Query(default=6, ge=1, le=10)):
    articles = news.refresh()[:limit]
    return _intelligence_call(intelligence.discover_topics, articles, topic_count)


@app.get("/api/classification")
def classification():
    return _intelligence_call(intelligence.classify_articles, news.refresh())


@app.get("/api/knowledge-graph/{article_id}")
def article_knowledge_graph(article_id: str):
    article = news.get_article(article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    related = _retrieve(article.get("title", ""), exclude_id=article_id, limit=5)
    return _intelligence_call(intelligence.knowledge_graph, [article, *related])


@app.get("/api/intelligence/{article_id}")
def article_intelligence(article_id: str):
    article = news.get_article(article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    text = news.article_text(article)
    combined_text = f"{article.get('title', '')}\n{article.get('summary', '')}\n{text}"
    nlp_result = _intelligence_call(intelligence.analyze_nlp, combined_text)
    return _intelligence_call(lambda: {
        "entities": nlp_result["entities"],
        "sentiment": intelligence.sentiment(combined_text),
        "keywords": _article_keywords(article, text),
        "lemmas": nlp_result["lemmas"][:100],
    })


@app.get("/api/profile/interests")
def get_interests(uid: str = Depends(require_user)):
    _need_db()
    profile = _profile_data(uid, "interests")
    return {"interests": profile.get("interests") or []}


@app.get("/api/profile/preferences")
def get_preferences(uid: str = Depends(require_user)):
    _need_db()
    data = _profile_data(uid, "interests,system_language,language,ai_language,journalism_fields,onboarding_completed")
    system_language = data.get("system_language") or data.get("language") or "en"
    news_preferences = data.get("interests") or []
    return {
        "interests": news_preferences,
        "news_preferences": news_preferences,
        "journalism_fields": data.get("journalism_fields") or [],
        "onboarding_completed": data.get("onboarding_completed") or False,
        "system_language": system_language,
        "language": system_language,
        "ai_language": data.get("ai_language") or "en",
    }


@app.put("/api/profile/preferences")
def update_preferences(body: PreferencesIn, uid: str = Depends(require_user)):
    _need_db()
    if all(value is None for value in (
        body.interests, body.news_preferences, body.language, body.system_language, body.ai_language,
        body.journalism_fields, body.onboarding_completed,
    )):
        raise HTTPException(422, "At least one preference is required.")
    profile = {"id": uid}
    result = {}
    if body.interests is not None and body.news_preferences is not None and body.interests != body.news_preferences:
        raise HTTPException(422, "Provide either interests or news_preferences, not conflicting values.")
    selected_news_preferences = body.news_preferences if body.news_preferences is not None else body.interests
    if selected_news_preferences is not None:
        invalid = sorted(set(selected_news_preferences) - set(AVAILABLE_INTERESTS))
        if invalid:
            raise HTTPException(422, f"Unsupported interests: {', '.join(invalid)}")
        interests = list(dict.fromkeys(selected_news_preferences))
        profile["interests"] = interests
        result["interests"] = interests
        result["news_preferences"] = interests
    if body.system_language is not None and body.language is not None and body.system_language != body.language:
        raise HTTPException(422, "Provide either system_language or language, not conflicting values.")
    selected_system_language = body.system_language if body.system_language is not None else body.language
    if selected_system_language is not None:
        if selected_system_language not in AVAILABLE_LANGUAGES:
            raise HTTPException(422, "Unsupported language. Choose English, Filipino, or Bisaya.")
        profile["system_language"] = selected_system_language
        profile["language"] = selected_system_language
        result["system_language"] = selected_system_language
        result["language"] = selected_system_language
    if body.ai_language is not None:
        if body.ai_language not in AVAILABLE_LANGUAGES:
            raise HTTPException(422, "Unsupported AI language. Choose English, Filipino, or Bisaya.")
        profile["ai_language"] = body.ai_language
        result["ai_language"] = body.ai_language
    journalism_fields = body.journalism_fields
    if journalism_fields is not None:
        invalid_fields = sorted(set(journalism_fields) - set(AVAILABLE_JOURNALISM_FIELDS))
        if invalid_fields:
            raise HTTPException(422, f"Unsupported journalism fields: {', '.join(invalid_fields)}")
        if len(set(journalism_fields)) > 3:
            raise HTTPException(422, "Choose no more than three journalism fields.")
        normalized_fields = list(dict.fromkeys(journalism_fields))
        profile["journalism_fields"] = normalized_fields
        result["journalism_fields"] = normalized_fields
    if body.onboarding_completed is not None:
        profile["onboarding_completed"] = body.onboarding_completed
        result["onboarding_completed"] = body.onboarding_completed
    try:
        sb.table("profiles").upsert(profile).execute()
    except APIError as exc:
        if _schema_gap(exc):
            raise HTTPException(
                503,
                "MIRA profile preference columns are missing. Run "
                "supabase/migrations/20261121_ai_language.sql and "
                "supabase/migrations/20261121_system_language.sql in the Supabase SQL Editor.",
            ) from exc
        raise HTTPException(
            503,
            f"Could not save your profile preferences: {getattr(exc, 'message', str(exc))}",
        ) from exc
    return result


@app.put("/api/profile/interests")
def update_interests(body: InterestsIn, uid: str = Depends(require_user)):
    _need_db()
    invalid = sorted(set(body.interests) - set(AVAILABLE_INTERESTS))
    if invalid:
        raise HTTPException(422, f"Unsupported interests: {', '.join(invalid)}")
    interests = list(dict.fromkeys(body.interests))
    sb.table("profiles").upsert({"id": uid, "interests": interests}).execute()
    return {"interests": interests}


@app.post("/api/admin/news/refresh")
def refresh_news(x_refresh_token: str | None = Header(default=None)):
    if not NEWS_REFRESH_TOKEN:
        raise HTTPException(503, "NEWS_REFRESH_TOKEN is not configured on the backend.")
    if not x_refresh_token or not hmac.compare_digest(
        x_refresh_token.encode("utf-8"), NEWS_REFRESH_TOKEN.encode("utf-8")
    ):
        raise HTTPException(401, "A valid news refresh token is required.")
    try:
        news.refresh(force=True)
    except Exception as exc:
        raise HTTPException(502, f"News collection or Supabase storage failed: {exc}") from exc
    return news.refresh_status()


@app.get("/api/articles/{article_id}")
def article(article_id: str):
    a = news.get_article(article_id)
    if not a:
        raise HTTPException(404, "Article not found")
    return a


@app.get("/api/articles/{article_id}/image")
def article_image(article_id: str, accept: str | None = Header(default=None)):
    a = news.get_article(article_id)
    if not a:
        raise HTTPException(404, "Article not found")
    image_url = a.get("image")
    if not image_url:
        raise HTTPException(404, "No publisher photo is available for this article")
    try:
        accepted_formats = (accept or "").lower()
        content, media_type = news.fetch_article_image(
            image_url,
            supports_avif="image/avif" in accepted_formats,
            publisher_url=a.get("url"),
        )
        content, media_type = news.optimize_article_image(
            content,
            media_type,
            supports_webp="image/webp" in accepted_formats,
        )
    except ValueError as exc:
        logger.warning("Could not serve publisher image for article %s: %s", article_id, exc)
        raise HTTPException(502, str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.warning("Could not retrieve publisher image for article %s: %s", article_id, exc)
        raise HTTPException(502, "The publisher photo could not be retrieved") from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
            "Vary": "Accept",
        },
    )


@app.get("/api/compare/{article_id}")
def compare_coverage(article_id: str, limit: int = Query(default=5, ge=1, le=10)):
    article = news.get_article(article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    corpus = news.list_articles(None, None, None, limit=1000)
    related = intelligence.content_recommendations(
        corpus, [article.get("title", ""), article.get("summary", "")], limit=len(corpus)
    )
    reports = [
        report for report in related
        if report.get("id") != article_id and report.get("source") != article.get("source")
    ][:limit]
    return {
        "article": article,
        "reports": [
            {
                "id": report.get("id"),
                "title": report.get("title"),
                "source": report.get("source"),
                "summary": report.get("summary"),
                "url": report.get("url"),
                "published": report.get("published"),
            }
            for report in reports
        ],
    }


@app.post("/api/chat")
def chat(
    body: ChatIn,
    uid: str | None = Depends(optional_user),
    stream: bool = False,
):
    msgs = [m.model_dump() for m in body.messages][-20:]
    if not msgs:
        raise HTTPException(422, "At least one message is required.")
    _validate_chat_targets(uid, body.conversation_id, body.project_id)
    mode = _requested_chat_mode(body.mode, msgs[-1]["content"])
    task = _chat_task(mode)
    research = _research_context(msgs, mode)
    sources = research["sources"]
    system = (
        _research_chat_system(mode, sources, research)
        + "\n\n" + _ai_language_instruction(uid)
    )
    if mode == "article_generation" and sources:
        research["article_prefix"] = _research_article_header(sources)
    model_messages = _messages_for_research_model(msgs)
    chunks = iter(())
    should_call_ai = (
        not research["insufficient"]
        and (not research["trend"] or research["analysis"])
    )
    if should_call_ai:
        _ai_call(ai._need_client, task)
        chunks = ai.chat_stream(model_messages, system, task) if stream else None
    if stream:
        return _stream_chat_response(
            chunks,
            sources,
            uid,
            body.conversation_id,
            "chat",
            None,
            msgs[-1]["content"],
            project_id=body.project_id,
            research=research,
        )
    model_reply = (
        _ai_call(ai.chat, model_messages, system, task)
        if chunks is None else ""
    )
    response_text = "\n\n".join(
        part for part in (
            research.get("article_prefix", ""),
            research["prefix"],
            model_reply,
        ) if part
    )
    reply = _append_research_source_references(
        response_text,
        sources,
        include_all_sources=bool(research.get("include_all_sources")),
    )
    reply = _with_research_context(
        reply, research["source_ids"], research["trend_ids"]
    )
    conv = _save_turn(
        uid, body.conversation_id, "chat", None, msgs[-1]["content"], reply,
        project_id=body.project_id,
    )
    return {"reply": reply, "conversation_id": conv}


@app.post("/api/chat/upload")
async def chat_upload(
    messages: str = Form(...),
    files: list[UploadFile] = File(...),
    conversation_id: str | None = Form(None),
    project_id: str | None = Form(None),
    mode: str = Form("auto"),
    stream: bool = False,
    uid: str | None = Depends(optional_user),
):
    try:
        body = ChatIn.model_validate({
            "messages": json.loads(messages),
            "conversation_id": conversation_id,
            "project_id": project_id,
            "mode": mode,
        })
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Chat messages must be valid JSON.") from exc
    msgs = [message.model_dump() for message in body.messages][-20:]
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(422, "End the message with a user prompt before uploading.")
    if not 1 <= len(files) <= 3:
        raise HTTPException(422, "Upload between one and three files.")
    _validate_chat_targets(uid, body.conversation_id, body.project_id)
    mode = _requested_chat_mode(body.mode, msgs[-1]["content"])
    allowed_types = {
        "application/pdf",
        "image/jpeg", "image/png", "image/webp",
        "audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/webm",
        "text/plain", "text/markdown",
    }
    max_file_bytes = 10 * 1024 * 1024
    total_bytes = 0
    attachments = []
    for upload in files:
        mime_type = upload.content_type or ""
        if mime_type not in allowed_types:
            raise HTTPException(415, "Use PDF, image, audio, or plain-text files.")
        data = await upload.read(max_file_bytes + 1)
        if not data or len(data) > max_file_bytes:
            raise HTTPException(413, "Each upload must be between 1 byte and 10 MB.")
        total_bytes += len(data)
        if total_bytes > 15 * 1024 * 1024:
            raise HTTPException(413, "The combined upload size cannot exceed 15 MB.")
        if mime_type.startswith("text/"):
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(415, "Text files must use UTF-8 encoding.") from exc
        attachments.append({
            "name": _clean_upload_name(upload.filename),
            "mime_type": mime_type,
            "data": data,
        })
    await asyncio.gather(*(upload.close() for upload in files))
    has_images = any(item["mime_type"].startswith("image/") for item in attachments)
    task = _chat_task(
        mode,
        has_images=has_images,
    )
    _ai_call(ai._need_client, task)
    user_context = _upload_retrieval_context(msgs)
    query = _upload_retrieval_query(user_context, attachments)
    sources = _retrieve(
        query,
        limit=ask_story_research.requested_source_count(msgs[-1]["content"]),
        strict_image_relevance=has_images,
    )
    system = _chat_system(mode, sources) + "\n\n" + _ai_language_instruction(uid)
    if has_images:
        system += (
            "\n\nFor uploaded-image analysis, cite a retrieved source only if it directly "
            "addresses the image's identified event or claim and supports the point being made. "
            "A keyword overlap alone is not evidence. If no directly relevant source was "
            "retrieved, say so plainly. Never invent source titles, links, or citations."
        )
    if stream:
        return _stream_chat_response(
            ai.chat_with_files_stream(msgs, attachments, system, task),
            sources,
            uid,
            body.conversation_id,
            "chat",
            None,
            msgs[-1]["content"],
            project_id=body.project_id,
            uploads_retained=False,
        )
    reply = ai.append_source_references(
        _ai_call(ai.chat_with_files, msgs, attachments, system, task), sources
    )
    conv = _save_turn(
        uid, body.conversation_id, "chat", None, msgs[-1]["content"], reply,
        project_id=body.project_id,
    )
    return {"reply": reply, "conversation_id": conv, "uploads_retained": False}


@app.post("/api/ask")
def ask(
    body: AskIn,
    uid: str | None = Depends(optional_user),
    stream: bool = False,
):
    a = news.get_article(body.article_id, enrich_image=False)
    if not a:
        raise HTTPException(404, "Article not found")
    msgs = [m.model_dump() for m in body.messages][-20:]
    if not msgs:
        raise HTTPException(422, "At least one message is required.")
    query = msgs[-1]["content"] if msgs else a.get("title", "")
    source_count = ask_story_research.requested_source_count(query)
    mode = _requested_chat_mode(body.mode, query)
    task = "article_generation" if mode == "article_generation" else "story_chat"
    task = ask_story.classify_task(query) if task == "story_chat" else task
    deep_research = ask_story.requires_deep_research(task, query)
    retrieval_query = f"{a.get('title', '')}\n{query}".strip()
    related_articles = _retrieve(
        retrieval_query,
        exclude_id=body.article_id,
        limit=source_count,
    )
    research_disclosure = None
    if deep_research:
        sources, research_disclosure = ask_story_research.research_sources(
            a, query, related_articles, limit=source_count
        )
    else:
        sources = ask_story_research.related_sources(
            a, query, related_articles, limit=source_count
        )
    article_text_is_summary = not deep_research
    article_context = (
        a.get("summary") or ""
        if article_text_is_summary
        else news.article_text(a)
    )
    system = ask_story.story_system(
        a,
        article_context,
        sources,
        research_disclosure=research_disclosure,
        deep_research=deep_research,
        source_count=source_count,
        article_text_is_summary=article_text_is_summary,
    )
    system += "\n\n" + _ai_language_instruction(uid)
    if stream:
        def event(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        def generate():
            response_parts = []
            try:
                for chunk, _model in ask_story.generate_stream(
                    msgs, system, task=task, article_id=body.article_id
                ):
                    response_parts.append(chunk)
                    yield event({"type": "token", "text": chunk})
                reply = ask_story.append_sources(
                    "".join(response_parts),
                    sources,
                    include_all_sources=deep_research,
                )
                conv = _save_story_turn(
                    uid, body.conversation_id, a, msgs[-1]["content"], reply
                )
                yield event({"type": "done", "reply": reply, "conversation_id": conv})
            except HTTPException as exc:
                yield event({"type": "error", "message": str(exc.detail)})
            except ask_story.AskStoryFailure as exc:
                yield event({"type": "error", "message": str(exc)})
            except Exception as exc:
                logger.exception("Ask Story streaming request failed")
                yield event({"type": "error", "message": f"Ask Story request failed: {exc}"})

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        reply, _model = ask_story.generate(
            msgs, system, task=task, article_id=body.article_id
        )
    except ask_story.AskStoryFailure as exc:
        raise HTTPException(503, str(exc)) from exc
    reply = ask_story.append_sources(
        reply, sources, include_all_sources=deep_research
    )
    conv = _save_story_turn(
        uid, body.conversation_id, a, msgs[-1]["content"], reply
    )
    return {"reply": reply, "conversation_id": conv}


@app.post("/api/analyze/{article_id}")
def analyze(article_id: str, uid: str | None = Depends(optional_user)):
    a = news.get_article(article_id)
    if not a:
        raise HTTPException(404, "Article not found")
    text = news.article_text(a)
    nlp_result = _intelligence_call(intelligence.analyze_nlp, f"{a.get('title', '')}\n{text}")
    nlp_features = _intelligence_call(lambda: {
        "entities": nlp_result["entities"],
        "sentiment": intelligence.sentiment(text),
        "keywords": _article_keywords(a, text),
    })
    related_articles = _retrieve(
        a.get("title", ""), exclude_id=article_id, limit=12
    )
    sources, research_disclosure = ask_story_research.research_sources(
        a,
        "Analyze the event's background, people involved, effects, responses, and unanswered questions.",
        related_articles,
    )
    prompt = (
        "Analyze this selected news story for journalists. Return valid JSON with these keys: "
        "main_issue, key_points, people_orgs, locations, claims_to_verify, background, "
        "implications, perspectives, angles, cited_sources. Do not invent facts. "
        "Use cited_sources only as IDs S1, S2, and so on."
    )
    messages = [{
        "role": "user",
        "content": prompt,
    }]
    system = ask_story.story_system(
        a,
        text,
        sources,
        research_disclosure=research_disclosure,
    )
    system += "\n\n" + _ai_language_instruction(uid)
    try:
        reply, _model = ask_story.generate(
            messages, system, task="news_analysis", article_id=article_id
        )
        result = json.loads(reply)
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object")
    except ask_story.AskStoryFailure as exc:
        raise HTTPException(503, str(exc)) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(502, "Ask Story provider returned invalid analysis JSON.") from exc
    result["cited_sources"] = [
        {
            "id": f"S{index}",
            "title": source.get("title", ""),
            "source": source.get("source", ""),
            "url": source.get("url", ""),
        }
        for index, source in enumerate(sources, 1)
        if f"S{index}" in result.get("cited_sources", [])
    ]
    result["nlp"] = nlp_features
    return result


@app.post("/api/summarize/{article_id}")
def summarize_article(article_id: str, uid: str | None = Depends(optional_user)):
    article = news.get_article(article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    sources = _retrieve(article.get("title", ""), exclude_id=article_id, limit=4)
    system = ask_story.story_system(article, news.article_text(article), sources)
    system += "\n\n" + _ai_language_instruction(uid)
    try:
        summary, _model = ask_story.generate(
            [{"role": "user", "content": "Write a concise factual summary of this selected news story."}],
            system,
            task="news_summarization",
            article_id=article_id,
        )
    except ask_story.AskStoryFailure as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "summary": summary,
        "sources": [
            {"id": f"S{i}", "title": source.get("title", ""),
             "source": source.get("source", ""), "url": source.get("url", "")}
            for i, source in enumerate(sources, 1)
        ],
    }


# ---- Accounts: favorites, history, conversations ----
def _need_db():
    if sb is None:
        raise HTTPException(503, "Supabase is not configured on the backend.")


def _schema_gap(exc: APIError) -> bool:
    return getattr(exc, "code", None) in {"42703", "42P01", "PGRST204", "PGRST205"}


def _profile_data(uid: str, columns: str) -> dict:
    _need_db()
    requested = [column.strip() for column in columns.split(",") if column.strip()]
    if not requested:
        return {}
    try:
        result = sb.table("profiles").select(",".join(requested)).eq("id", uid).execute()
        return result.data[0] if result.data else {}
    except APIError as exc:
        if not _schema_gap(exc):
            raise
        try:
            result = sb.table("profiles").select("*").eq("id", uid).execute()
        except APIError as fallback_error:
            if _schema_gap(fallback_error):
                return {}
            raise
        if not result.data:
            return {}
        profile = result.data[0]
        return {column: profile[column] for column in requested if column in profile}


def _optional_rows(table: str, build_query) -> list:
    _need_db()
    try:
        return build_query(sb.table(table)).execute().data or []
    except APIError as exc:
        if _schema_gap(exc):
            logger.warning("Skipping unavailable Supabase table %s: %s", table, getattr(exc, "message", exc))
            return []
        raise


def _require_projects_migration(exc: APIError) -> None:
    if getattr(exc, "code", None) == "PGRST205":
        raise HTTPException(
            503,
            "Chat projects are not set up in Supabase. Run "
            "supabase/migrations/20261111_chat_projects.sql in the Supabase SQL Editor.",
        ) from exc


def _conversation_rows(uid: str, conversation_id: str | None = None):
    try:
        query = sb.table("conversations").select(
            "id,kind,title,project_id,created_at"
        )
        if conversation_id:
            query = query.eq("id", conversation_id)
        return query.eq("user_id", uid).eq("kind", "chat").execute().data
    except APIError as exc:
        if getattr(exc, "code", None) not in {"PGRST204", "42703"}:
            raise
    query = sb.table("conversations").select("id,kind,title,created_at")
    if conversation_id:
        query = query.eq("id", conversation_id)
    return query.eq("user_id", uid).eq("kind", "chat").execute().data


@app.get("/api/favorites")
def list_favorites(uid: str = Depends(require_user)):
    _need_db()
    rows = sb.table("favorites").select("*").eq("user_id", uid).order("saved_at", desc=True).execute()
    return {"favorites": rows.data}


@app.post("/api/favorites")
def add_favorite(a: dict, uid: str = Depends(require_user)):
    _need_db()
    row = {"user_id": uid, "article_id": a["id"], "title": a.get("title"), "source": a.get("source"),
           "url": a.get("url"), "summary": a.get("summary")}
    sb.table("favorites").upsert(row).execute()
    return {"ok": True}


@app.delete("/api/favorites/{article_id}")
def remove_favorite(article_id: str, uid: str = Depends(require_user)):
    _need_db()
    sb.table("favorites").delete().eq("user_id", uid).eq("article_id", article_id).execute()
    return {"ok": True}


@app.post("/api/history")
def add_history(a: dict, uid: str | None = Depends(optional_user)):
    if not uid or sb is None:
        return {"ok": False}
    sb.table("reading_history").insert({"user_id": uid, "article_id": a["id"], "title": a.get("title"),
                                        "source": a.get("source"), "url": a.get("url")}).execute()
    return {"ok": True}


@app.get("/api/history")
def list_history(uid: str = Depends(require_user)):
    _need_db()
    rows = sb.table("reading_history").select("*").eq("user_id", uid).order("viewed_at", desc=True).limit(30).execute()
    return {"history": rows.data}


@app.delete("/api/history")
def clear_history(uid: str = Depends(require_user)):
    _need_db()
    sb.table("reading_history").delete().eq("user_id", uid).execute()
    sb.table("search_history").delete().eq("user_id", uid).execute()
    return {"ok": True}


@app.get("/api/search-history")
def list_search_history(uid: str = Depends(require_user)):
    _need_db()
    searches = _optional_rows(
        "search_history",
        lambda query: query.select("*").eq(
            "user_id", uid
        ).order("searched_at", desc=True).limit(50),
    )
    return {"searches": searches}


@app.get("/api/conversations")
def list_conversations(uid: str = Depends(require_user)):
    _need_db()
    rows = _conversation_rows(uid)
    return {
        "conversations": sorted(
            rows, key=lambda row: row.get("created_at") or "", reverse=True
        )[:100]
    }


@app.post("/api/projects")
def create_project(body: ProjectIn, uid: str = Depends(require_user)):
    _need_db()
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Project title cannot be blank.")
    try:
        row = sb.table("projects").insert({
            "user_id": uid,
            "title": title,
        }).execute()
    except APIError as exc:
        _require_projects_migration(exc)
        raise
    return {"project": row.data[0]}


@app.get("/api/projects")
def list_projects(uid: str = Depends(require_user)):
    _need_db()
    try:
        rows = sb.table("projects").select(
            "id,title,created_at"
        ).eq("user_id", uid).order("created_at", desc=True).limit(100).execute()
    except APIError as exc:
        _require_projects_migration(exc)
        raise
    return {"projects": rows.data}


@app.post("/api/conversations")
def create_conversation(
    body: ConversationIn, uid: str = Depends(require_user),
):
    _need_db()
    _validate_chat_targets(uid, None, body.project_id)
    conversation = {
        "user_id": uid,
        "kind": "chat",
        "title": "New chat",
    }
    if body.project_id:
        conversation["project_id"] = body.project_id
    row = sb.table("conversations").insert(conversation).execute()
    return {"conversation": row.data[0]}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, uid: str = Depends(require_user)):
    _need_db()
    rows = _conversation_rows(uid, conversation_id)
    if not rows:
        raise HTTPException(404, "Conversation not found.")
    conversation = rows[0]
    messages = sb.table("messages").select(
        "id,role,content,created_at"
    ).eq("conversation_id", conversation_id).order("created_at").execute()
    return {"conversation": conversation, "messages": messages.data}


@app.get("/api/ask/conversations")
def list_ask_story_conversations(
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    uid: str = Depends(require_user),
):
    _need_db()
    rows = sb.table("conversations").select(
        "id,title,article_id,created_at"
    ).eq("user_id", uid).eq("kind", "story").order(
        "created_at", desc=True
    ).range(offset, offset + limit - 1).execute().data or []
    return {"conversations": rows, "has_more": len(rows) == limit}


@app.get("/api/ask/conversations/{conversation_id}")
def get_ask_story_conversation(
    conversation_id: str,
    uid: str = Depends(require_user),
):
    _need_db()
    result = sb.table("conversations").select(
        "id,title,article_id,created_at"
    ).eq("id", conversation_id).eq("user_id", uid).eq(
        "kind", "story"
    ).maybe_single().execute()
    if not result.data:
        raise HTTPException(404, "Ask Story conversation not found.")
    messages = sb.table("messages").select(
        "id,role,content,created_at"
    ).eq("conversation_id", conversation_id).order("created_at").execute()
    return {"conversation": result.data, "messages": messages.data}
