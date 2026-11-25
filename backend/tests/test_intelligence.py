import asyncio
import json
import re
import unittest
from io import BytesIO
from datetime import date, datetime, timedelta, timezone
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import httpx
from PIL import Image
from fastapi import UploadFile
from postgrest.exceptions import APIError
from starlette.datastructures import Headers

from app import ai, config, feeds, intelligence, main, news, search_intelligence


def articles_for_topics():
    return [
        {"id": "climate-1", "title": "Climate scientists study warming oceans",
         "summary": "Researchers measure rising sea temperatures."},
        {"id": "climate-2", "title": "Climate research tracks coastal warming",
         "summary": "Scientists report changing ocean temperatures."},
        {"id": "sports-1", "title": "Football team wins championship",
         "summary": "The players celebrated a tournament victory."},
        {"id": "sports-2", "title": "Basketball league announces finals",
         "summary": "Athletes prepare for the championship game."},
        {"id": "health-1", "title": "Hospital expands public health services",
         "summary": "Doctors add community clinics for patients."},
        {"id": "health-2", "title": "Health researchers study disease prevention",
         "summary": "Medical teams evaluate prevention programs."},
    ]


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        ai.providers.reset_health()
        with ai._response_cache_lock:
            ai._response_cache.clear()

    def test_search_intelligence_extracts_context_and_historical_year_ranges(self):
        intent = search_intelligence.understand_query(
            "Show me the news about Rodrigo Roa Duterte during his war on drugs."
        )
        self.assertEqual(intent["query"], "Rodrigo Roa Duterte war drugs")
        dated = search_intelligence.understand_query(
            "Show me news about Alexandra Eala from 2023 to 2024"
        )
        self.assertEqual(dated["query"], "Alexandra Eala")
        self.assertEqual(dated["from_date"], date(2023, 1, 1))
        self.assertEqual(dated["to_date"], date(2024, 12, 31))
        series_title = search_intelligence.understand_query("agri-ignite year 2")
        self.assertEqual(series_title["query"], "agri-ignite year 2")
        self.assertIsNone(series_title["from_date"])
        self.assertIsNone(series_title["to_date"])

    def test_search_matches_mindanao_sentinel_story_metadata(self):
        story = {
            "id": "agri-ignite-year-2",
            "title": "Agri-IGNITE Year 2 showcases digital innovations for farming and fisheries in Caraga",
            "description": "Fisheries agencies in Butuan pilot solar-powered cold storage.",
            "source": "The Mindanao Sentinel",
            "category": "Agriculture",
            "topics": ["Agriculture"],
            "people": ["Maria Santos"],
            "location": "Butuan City",
        }
        unrelated = {
            "id": "sports",
            "title": "Basketball league opens championship season",
            "summary": "Teams prepare for the final match.",
            "source": "Sports Daily",
        }

        for query in (
            "agri-ignite",
            "solar-powered cold storage",
            "Maria Santos",
            "Butuan City",
            "Agriculture",
            "The Mindanao Sentinel",
        ):
            with self.subTest(query=query):
                ranked, _ = intelligence.fast_search(query, [story, unrelated], limit=1)
                self.assertEqual([article["id"] for article in ranked], ["agri-ignite-year-2"])

    def test_exact_archive_matches_skip_live_search_and_return_immediately(self):
        story = {
            "id": "agri-ignite-year-2",
            "title": "Agri-IGNITE Year 2 showcases digital innovations for farming and fisheries in Caraga",
            "summary": "Agri-IGNITE Year 2 showcases digital innovations for farming and fisheries in Caraga The Mindanao Sentinel",
            "source": "The Mindanao Sentinel",
            "section": "regional",
            "url": "https://example.test/agri-ignite",
            "category": "Agriculture",
            "topics": ["Agriculture"],
            "published": "2026-11-20T13:00:00Z",
        }
        unrelated = {
            "id": "sports",
            "title": "Basketball league opens championship season",
            "summary": "Teams prepare for the final match.",
            "source": "Sports Daily",
            "section": "national",
            "url": "https://example.test/sports",
        }
        with (
            patch.dict(news._cache, {"items": [story, unrelated], "stored_loaded": True}),
            patch.dict(news._by_id, {}, clear=True),
            patch.dict(news._search_cache, {}, clear=True),
            patch.object(news, "sb", None),
            patch.object(news, "_schedule_image_enrichment"),
            patch.object(news, "_pull_feeds", new=AsyncMock()) as pull_feeds,
            patch.object(
                news,
                "hybrid_search",
                side_effect=lambda query, articles, limit, **_kwargs: (
                    intelligence.fast_search(query, articles, limit)[0],
                    "bm25+sentence-transformers",
                ),
            ),
        ):
            result = news.search_discovery("agri-ignite", limit=10)

        self.assertEqual([article["id"] for article in result["articles"]], ["agri-ignite-year-2"])
        pull_feeds.assert_not_awaited()

    def test_default_cors_origins_include_nextjs_fallback_port(self):
        self.assertIn("http://localhost:3001", config._cors_origins(None))
        self.assertIn("http://127.0.0.1:3001", config._cors_origins(None))
        configured = config._cors_origins(
            "http://localhost:3000,http://127.0.0.1:3000"
        )
        self.assertIn("http://localhost:3001", configured)
        self.assertIn("http://127.0.0.1:3001", configured)

    def test_search_discovery_fetches_query_results_and_archives_source_metadata(self):
        article = {
            "id": "eala-story",
            "title": "Alexandra Eala advances in 2024 tennis tournament",
            "summary": "The Filipino tennis player advanced to the next round.",
            "source": "Rappler",
            "section": "national",
            "url": "https://news.google.com/rss/articles/eala-story",
            "canonical_url": "https://news.google.com/rss/articles/eala-story",
            "category": "Sports",
            "image_url": None,
            "published": "2024-06-10T00:00:00Z",
            "author": "News Desk",
        }
        supabase = MagicMock()
        with (
            patch.dict(news._cache, {"items": [], "stored_loaded": True}),
            patch.dict(news._by_id, {}, clear=True),
            patch.dict(news._search_cache, {}, clear=True),
            patch.object(news, "sb", supabase),
            patch.object(news, "_load_existing_articles", return_value={}),
            patch.object(news, "_schedule_image_enrichment") as schedule_images,
            patch.object(
                news,
                "hybrid_search",
                side_effect=lambda _query, articles, limit, **_kwargs: (
                    articles[:limit], "bm25+sentence-transformers",
                ),
            ),
            patch.object(
                news,
                "_pull_feeds",
                new=AsyncMock(return_value=[([article], None)]),
            ) as pull_feeds,
        ):
            result = news.search_discovery(
                "Show me news about Alexandra Eala in 2024",
                limit=10,
            )

        self.assertEqual([item["id"] for item in result["articles"]], ["eala-story"])
        self.assertEqual(result["articles"][0]["author"], "News Desk")
        schedule_images.assert_called_once()
        self.assertEqual(
            [article["id"] for article in schedule_images.call_args.args[0]],
            ["eala-story"],
        )
        self.assertIn("image_enrichment_running", result)
        supabase.table.return_value.upsert.assert_called_once()
        archived = supabase.table.return_value.upsert.call_args.args[0]
        self.assertEqual(archived[0]["source"], "Rappler")
        self.assertEqual(archived[0]["author"], "News Desk")
        feed_url = pull_feeds.await_args.args[0][0]["url"]
        self.assertIn("after%3A2024-01-01", feed_url)
        self.assertIn("before%3A2025-01-01", feed_url)
        self.assertEqual(pull_feeds.await_args.args[0][0]["timeout_seconds"], 5)
        self.assertEqual(pull_feeds.await_args.args[0][0]["retries"], 0)

    def test_search_discovery_falls_back_to_archive_when_live_rss_has_no_results(self):
        archived = {
            "id": "archived-duterte",
            "title": "Duterte war on drugs investigation",
            "summary": "A historical report on the investigation.",
            "source": "Rappler",
            "section": "national",
            "url": "https://rappler.com/news/archives/duterte-investigation",
            "published": "2019-03-01T00:00:00Z",
        }
        with (
            patch.dict(news._cache, {"items": [archived], "stored_loaded": True}),
            patch.dict(news._by_id, {}, clear=True),
            patch.dict(news._search_cache, {}, clear=True),
            patch.object(news, "sb", None),
            patch.object(news, "_schedule_image_enrichment"),
            patch.object(
                news,
                "hybrid_search",
                side_effect=lambda _query, articles, limit, **_kwargs: (
                    articles[:limit], "bm25+sentence-transformers",
                ),
            ),
            patch.object(
                news,
                "_pull_feeds",
                new=AsyncMock(return_value=[([], "Feed returned no entries")]),
            ),
        ):
            result = news.search_discovery("Duterte war on drugs", period="historical")

        self.assertEqual([item["id"] for item in result["articles"]], ["archived-duterte"])
        self.assertEqual(
            result["source_errors"],
            [{"source": "Google News Search", "error": "Feed returned no entries"}],
        )

    def test_search_discovery_filters_and_paginates_historical_archive_results(self):
        archived = [
            {
                "id": "local-eala",
                "title": "Alexandra Eala local tennis update",
                "summary": "Career report.",
                "source": "PNA",
                "section": "local",
                "url": "https://example.test/local",
                "published": "2024-01-01T00:00:00Z",
                "topics": ["Sports"],
            },
            {
                "id": "national-eala",
                "title": "Alexandra Eala national tennis update",
                "summary": "Career report.",
                "source": "Rappler",
                "section": "national",
                "url": "https://example.test/national",
                "published": "2020-01-01T00:00:00Z",
                "topics": ["Sports"],
            },
            {
                "id": "international-eala",
                "title": "Alexandra Eala international tennis update",
                "summary": "Career report.",
                "source": "BBC",
                "section": "international",
                "url": "https://example.test/international",
                "published": "2023-01-01T00:00:00Z",
                "topics": ["Sports"],
            },
        ]
        with (
            patch.dict(news._cache, {"items": archived, "stored_loaded": True}),
            patch.dict(news._by_id, {}, clear=True),
            patch.dict(news._search_cache, {}, clear=True),
            patch.object(news, "sb", None),
            patch.object(news, "_schedule_image_enrichment"),
            patch.object(
                news,
                "hybrid_search",
                side_effect=lambda _query, articles, limit, **_kwargs: (
                    articles[:limit], "bm25+sentence-transformers",
                ),
            ),
            patch.object(
                news,
                "_pull_feeds",
                new=AsyncMock(return_value=[([], "Feed returned no entries")]),
            ),
        ):
            first = news.search_discovery(
                "Alexandra Eala",
                scope="philippines",
                topic="Sports",
                from_date=date(2020, 1, 1),
                to_date=date(2024, 12, 31),
                sort="oldest",
                limit=1,
            )
            second = news.search_discovery(
                "Alexandra Eala",
                scope="philippines",
                topic="Sports",
                from_date=date(2020, 1, 1),
                to_date=date(2024, 12, 31),
                sort="oldest",
                limit=1,
                offset=1,
            )

        self.assertEqual(first["total"], 2)
        self.assertEqual([item["id"] for item in first["articles"]], ["national-eala"])
        self.assertEqual(first["next_offset"], 1)
        self.assertEqual([item["id"] for item in second["articles"]], ["local-eala"])
        self.assertIsNone(second["next_offset"])

    def test_search_api_forwards_filters_and_rejects_reversed_date_ranges(self):
        with patch.object(main.news, "search_discovery", return_value={"articles": []}) as search:
            result = main.search_articles(
                q="Philippine elections",
                section=None,
                topic="Politics",
                scope="philippines",
                period="historical",
                from_date=date(2016, 1, 1),
                to_date=date(2016, 12, 31),
                sort="oldest",
                limit=20,
                offset=10,
                uid=None,
            )
        self.assertEqual(result, {"articles": []})
        self.assertEqual(search.call_args.kwargs["scope"], "philippines")
        self.assertEqual(search.call_args.kwargs["from_date"], date(2016, 1, 1))
        self.assertEqual(search.call_args.kwargs["sort"], "oldest")

        with self.assertRaises(main.HTTPException) as raised:
            main.search_articles(
                q="Philippine elections",
                section=None,
                topic=None,
                scope="all",
                period="all",
                from_date=date(2020, 1, 1),
                to_date=date(2019, 1, 1),
                sort="relevance",
                limit=20,
                offset=0,
                uid=None,
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_feed_text_decodes_html_entities_for_readable_story_summaries(self):
        self.assertEqual(news._clean("News&nbsp;&nbsp; &amp; reporting"), "News & reporting")
        article = {
            "id": "article",
            "title": "Headline",
            "summary": "News&nbsp;&nbsp; &amp; reporting",
            "source": "Source",
            "section": "national",
            "url": "https://example.test/story",
        }
        self.assertEqual(news._public_article(article)["summary"], "News & reporting")

    def test_empty_cors_configuration_uses_local_development_origins(self):
        self.assertEqual(config._cors_origins(""), [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ])
        self.assertEqual(config._cors_origins("https://mira.example"), ["https://mira.example"])

    def test_retired_gemini_flash_model_is_upgraded(self):
        self.assertEqual(
            config._gemini_model("GEMINI_MODEL", "gemini-2.5-flash"),
            "gemini-3.5-flash",
        )

    def test_missing_projects_table_returns_migration_instructions(self):
        with self.assertRaises(main.HTTPException) as raised:
            main._require_projects_migration(APIError({
                "code": "PGRST205",
                "message": "Projects table missing",
            }))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("20261111_chat_projects.sql", raised.exception.detail)

    def test_profile_preferences_save_fields_topics_and_onboarding_state(self):
        supabase = MagicMock()
        body = main.PreferencesIn(
            interests=["Sports", "Health"],
            journalism_fields=["Sports Journalism", "News Writing"],
            onboarding_completed=True,
            language="en",
        )
        with patch.object(main, "_need_db"), patch.object(main, "sb", supabase):
            result = main.update_preferences(body, uid="user-1")

        supabase.table.return_value.upsert.assert_called_once_with({
            "id": "user-1",
            "interests": ["Sports", "Health"],
            "journalism_fields": ["Sports Journalism", "News Writing"],
            "onboarding_completed": True,
            "system_language": "en",
            "language": "en",
        })
        self.assertEqual(result["interests"], ["Sports", "Health"])
        self.assertEqual(result["journalism_fields"], ["Sports Journalism", "News Writing"])
        self.assertTrue(result["onboarding_completed"])

    def test_profile_preferences_default_when_user_has_no_profile_row(self):
        query = MagicMock()
        query.eq.return_value.execute.return_value = SimpleNamespace(data=[])
        supabase = MagicMock()
        supabase.table.return_value.select.return_value = query

        with patch.object(main, "_need_db"), patch.object(main, "sb", supabase):
            result = main.get_preferences(uid="user-without-profile")

        self.assertEqual(result, {
            "interests": [],
            "news_preferences": [],
            "journalism_fields": [],
            "onboarding_completed": False,
            "system_language": "en",
            "language": "en",
            "ai_language": "en",
        })

    def test_profile_data_uses_one_fallback_query_for_missing_columns(self):
        first_query = MagicMock()
        first_query.eq.return_value.execute.side_effect = APIError({
            "code": "PGRST204",
            "message": "Could not find the 'ai_language' column of 'profiles' in the schema cache",
        })
        fallback_query = MagicMock()
        fallback_query.eq.return_value.execute.return_value = SimpleNamespace(data=[{
            "interests": ["Sports"],
            "private_note": "not returned",
        }])
        profile_table = MagicMock()
        profile_table.select.side_effect = [first_query, fallback_query]
        supabase = MagicMock()
        supabase.table.return_value = profile_table

        with patch.object(main, "_need_db"), patch.object(main, "sb", supabase):
            result = main._profile_data("user-1", "interests,ai_language")

        self.assertEqual(
            [args.args for args in profile_table.select.call_args_list],
            [("interests,ai_language",), ("*",)],
        )
        self.assertEqual(result, {"interests": ["Sports"]})

    def test_profile_preferences_can_save_ai_language_independently(self):
        supabase = MagicMock()
        body = main.PreferencesIn(ai_language="ceb")
        with patch.object(main, "_need_db"), patch.object(main, "sb", supabase):
            result = main.update_preferences(body, uid="user-1")

        supabase.table.return_value.upsert.assert_called_once_with({
            "id": "user-1",
            "ai_language": "ceb",
        })
        self.assertEqual(result, {"ai_language": "ceb"})

    def test_profile_preferences_save_system_language_independently(self):
        supabase = MagicMock()
        body = main.PreferencesIn(system_language="fil")
        with patch.object(main, "_need_db"), patch.object(main, "sb", supabase):
            result = main.update_preferences(body, uid="user-1")

        supabase.table.return_value.upsert.assert_called_once_with({
            "id": "user-1",
            "system_language": "fil",
            "language": "fil",
        })
        self.assertEqual(result["system_language"], "fil")
        self.assertNotIn("ai_language", result)

    def test_profile_preferences_save_news_preferences_without_languages(self):
        supabase = MagicMock()
        body = main.PreferencesIn(
            news_preferences=["Sports", "Health"],
            journalism_fields=["News Writing"],
        )
        with patch.object(main, "_need_db"), patch.object(main, "sb", supabase):
            result = main.update_preferences(body, uid="user-1")

        supabase.table.return_value.upsert.assert_called_once_with({
            "id": "user-1",
            "interests": ["Sports", "Health"],
            "journalism_fields": ["News Writing"],
        })
        self.assertEqual(result["news_preferences"], ["Sports", "Health"])
        self.assertNotIn("system_language", result)
        self.assertNotIn("ai_language", result)

    def test_profile_preferences_reject_unsupported_languages(self):
        for field in ("system_language", "ai_language"):
            with self.subTest(field=field):
                with patch.object(main, "_need_db"):
                    with self.assertRaises(main.HTTPException) as raised:
                        main.update_preferences(
                            main.PreferencesIn(**{field: "es"}),
                            uid="user-1",
                        )
                self.assertEqual(raised.exception.status_code, 422)

    def test_profile_preferences_missing_columns_return_migration_instructions(self):
        supabase = MagicMock()
        supabase.table.return_value.upsert.return_value.execute.side_effect = APIError({
            "code": "PGRST204",
            "message": "Could not find the 'language' column of 'profiles' in the schema cache",
        })
        with patch.object(main, "_need_db"), patch.object(main, "sb", supabase):
            with self.assertRaises(main.HTTPException) as raised:
                main.update_preferences(
                    main.PreferencesIn(system_language="fil"),
                    uid="user-1",
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("20261121_ai_language.sql", raised.exception.detail)
        self.assertIn("20261121_system_language.sql", raised.exception.detail)

    def test_search_history_returns_empty_when_table_migration_is_missing(self):
        query = MagicMock()
        query.eq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.side_effect = APIError({
            "code": "PGRST205",
            "message": "Could not find the table 'public.search_history'",
        })
        supabase = MagicMock()
        supabase.table.return_value.select.return_value = query
        with patch.object(main, "_need_db"), patch.object(main, "sb", supabase):
            result = main.list_search_history(uid="user-1")

        self.assertEqual(result, {"searches": []})

    def test_ai_language_instruction_uses_saved_profile_language(self):
        with patch.object(main, "_profile_data", return_value={"ai_language": "fil"}):
            instruction = main._ai_language_instruction("user-1")

        self.assertIn("Respond in Filipino (Tagalog).", instruction)
        self.assertIn("natural, contemporary Filipino", instruction)

    def test_ai_language_instruction_is_independent_of_system_language(self):
        with patch.object(
            main, "_profile_data",
            return_value={"system_language": "fil", "ai_language": "ceb"},
        ) as profile_data:
            instruction = main._ai_language_instruction("user-1")

        profile_data.assert_called_once_with("user-1", "ai_language")
        self.assertIn("Respond in Cebuano (Bisaya).", instruction)
        self.assertIn("natural Cebuano/Bisaya grammar and expressions", instruction)

    def test_profile_preferences_reject_more_than_three_journalism_fields(self):
        body = main.PreferencesIn(
            interests=[],
            journalism_fields=["Sports Journalism", "News Writing", "Feature Writing", "Photojournalism"],
            language="en",
        )
        with patch.object(main, "_need_db"):
            with self.assertRaises(main.HTTPException) as raised:
                main.update_preferences(body, uid="user-1")

        self.assertEqual(raised.exception.status_code, 422)

    def test_existing_article_lookup_batches_urls_into_small_requests(self):
        urls = [f"https://news.example.test/story/{index}" for index in range(25)]
        query = MagicMock()
        query.in_.return_value.execute.side_effect = [
            SimpleNamespace(data=[
                {"canonical_url": url, "id": str(index)}
                for index, url in enumerate(urls[offset:offset + 10], start=offset)
            ])
            for offset in range(0, len(urls), 10)
        ]
        supabase = MagicMock()
        supabase.table.return_value.select.return_value = query

        with patch.object(news, "sb", supabase):
            rows = news._load_existing_articles(urls)

        calls = query.in_.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(len(call.args[1]) <= 10 for call in calls))
        self.assertEqual(set(rows), set(urls))

    def test_chat_history_falls_back_when_project_column_is_not_migrated(self):
        query = MagicMock()
        query.eq.return_value = query
        query.execute.side_effect = [
            APIError({"code": "42703", "message": "project_id does not exist"}),
            SimpleNamespace(data=[{"id": "chat-1", "title": "Saved chat"}]),
        ]
        supabase = MagicMock()
        supabase.table.return_value.select.return_value = query
        with patch.object(main, "sb", supabase):
            rows = main._conversation_rows("user-1")
        self.assertEqual(rows, [{"id": "chat-1", "title": "Saved chat"}])
        self.assertEqual(supabase.table.return_value.select.call_count, 2)

    def test_rss_image_extractor_finds_relative_embedded_images(self):
        image = news._image(
            {"content": [{"value": '<p>Story</p><img src="/images/report.jpg">'}]},
            "https://news.example.test/story",
        )
        self.assertEqual(image, "https://news.example.test/images/report.jpg")

    def test_rss_image_extractor_prefers_provided_thumbnail(self):
        image = news._image(
            {
                "media_content": [{"url": "https://cdn.example.test/original.jpg"}],
                "media_thumbnail": [{"url": "https://cdn.example.test/thumb.jpg"}],
            },
            "https://news.example.test/story",
        )
        self.assertEqual(image, "https://cdn.example.test/thumb.jpg")

    def test_rss_image_extractor_finds_lazy_loaded_image_sources(self):
        image = news._image(
            {"summary": (
                '<img src="/images/placeholder.gif" '
                'data-srcset="/images/report.webp 2x, /images/report.jpg 1x">'
            )},
            "https://news.example.test/story",
        )
        self.assertEqual(image, "https://news.example.test/images/report.webp")

    def test_article_image_parser_finds_itemprop_metadata_and_picture_source(self):
        response = SimpleNamespace(
            headers={"content-type": "text/html"},
            url="https://news.example.test/story",
            text=(
                '<meta itemprop="image" content="/images/cover.jpg">'
                '<picture><source srcset="/images/inline.webp 2x"></picture>'
            ),
            raise_for_status=lambda: None,
        )
        with patch.object(news.httpx, "get", return_value=response):
            image = news._page_image({"url": "https://news.example.test/story"})
        self.assertEqual(image, "https://news.example.test/images/cover.jpg")

    def test_rss_image_extractor_uses_image_metadata_before_inline_images(self):
        image = news._image(
            {"summary": (
                '<img src="https://news.example.test/body.jpg">'
                '<meta property="og:image" content="https://cdn.example.test/cover.jpg">'
            )},
            "https://news.example.test/story",
        )
        self.assertEqual(image, "https://cdn.example.test/cover.jpg")

    def test_article_page_image_uses_open_graph_metadata(self):
        response = SimpleNamespace(
            headers={"content-type": "text/html"},
            url="https://news.example.test/story",
            text='<meta property="og:image" content="//cdn.example.test/cover.jpg">',
            raise_for_status=lambda: None,
        )
        with patch.object(news.httpx, "get", return_value=response):
            image = news._page_image({"url": "https://news.example.test/story"})
        self.assertEqual(image, "https://cdn.example.test/cover.jpg")

    def test_google_news_article_url_resolves_to_publisher_article(self):
        google_url = "https://news.google.com/rss/articles/article-token?oc=5"
        signature_response = SimpleNamespace(
            text='<div data-n-a-sg="signature" data-n-a-ts="123456"></div>',
            raise_for_status=lambda: None,
        )
        result_payload = json.dumps([
            "garturlres", "https://publisher.example.test/story", 1,
        ])
        decoded_response = SimpleNamespace(
            text=")]}'\n\n" + json.dumps([
                ["wrb.fr", "Fbv4je", result_payload, None, None, None, "0"],
                ["di", 10],
            ]),
            raise_for_status=lambda: None,
        )
        with patch.object(
            news.httpx, "get", return_value=signature_response
        ) as get, patch.object(news.httpx, "post", return_value=decoded_response):
            resolved = news._decode_google_news_urls([google_url])
        self.assertEqual(
            resolved[google_url], "https://publisher.example.test/story"
        )
        self.assertIn("/rss/articles/article-token?", get.call_args.args[0])

    def test_google_news_story_uses_public_thumbnail_before_publisher_fallback(self):
        google_url = "https://news.google.com/rss/articles/article-token?oc=5"
        response = SimpleNamespace(
            headers={"content-type": "text/html"},
            url=google_url,
            text='<meta property="og:image" content="https://lh3.googleusercontent.com/story-photo">',
            raise_for_status=lambda: None,
        )
        with patch.object(news, "_decode_google_news_urls") as decode, patch.object(
            news.httpx, "get", return_value=response
        ) as get:
            image = news._page_image({"url": google_url})
        self.assertEqual(image, "https://lh3.googleusercontent.com/story-photo")
        self.assertEqual(get.call_args.args[0], google_url)
        decode.assert_not_called()

    def test_google_news_story_falls_back_to_publisher_page_for_image(self):
        google_url = "https://news.google.com/rss/articles/article-token?oc=5"
        publisher_url = "https://publisher.example.test/story"
        google_response = SimpleNamespace(
            headers={"content-type": "text/html"},
            url=google_url,
            text="<html></html>",
            raise_for_status=lambda: None,
        )
        publisher_response = SimpleNamespace(
            headers={"content-type": "text/html"},
            url=publisher_url,
            text='<meta property="og:image" content="/images/real-photo.jpg">',
            raise_for_status=lambda: None,
        )
        with patch.object(
            news, "_decode_google_news_urls", return_value={google_url: publisher_url}
        ), patch.object(
            news.httpx, "get", side_effect=[google_response, publisher_response]
        ) as get:
            image = news._page_image({"url": google_url})
        self.assertEqual(image, "https://publisher.example.test/images/real-photo.jpg")
        self.assertEqual(get.call_args.args[0], publisher_url)

    def test_google_news_site_icon_is_not_used_when_publisher_blocks_page_fetch(self):
        google_url = "https://news.google.com/rss/articles/article-token?oc=5"
        publisher_url = "https://publisher.example.test/story"
        blocked_response = httpx.Response(
            403, request=httpx.Request("GET", google_url)
        )
        with patch.object(
            news, "_decode_google_news_urls", return_value={google_url: publisher_url}
        ), patch.object(
            news.httpx, "get", side_effect=[
                blocked_response,
                httpx.Response(403, request=httpx.Request("GET", publisher_url)),
            ]
        ) as get:
            image = news._page_image({"url": google_url})
        self.assertIsNone(image)
        self.assertEqual(get.call_count, 2)

    def test_abs_cbn_image_host_is_allowed_by_image_proxy(self):
        image_url = (
            "https://od2-image-api.abs-cbn.com/prod/story-photo.png?w=1200&h=800"
        )
        response = SimpleNamespace(
            is_redirect=False,
            headers={"content-type": "image/webp"},
            content=b"photo",
            raise_for_status=lambda: None,
        )
        with patch.object(news.httpx, "get", return_value=response) as get:
            content, media_type = news.fetch_article_image(image_url)
        self.assertEqual(content, b"photo")
        self.assertEqual(media_type, "image/webp")
        self.assertEqual(get.call_args.args[0], image_url)

    def test_article_image_proxy_uses_publisher_referrer_and_sniffs_image_bytes(self):
        source = BytesIO()
        Image.new("RGB", (20, 10), color=(40, 100, 180)).save(source, format="JPEG")
        response = SimpleNamespace(
            is_redirect=False,
            headers={"content-type": "application/octet-stream"},
            content=source.getvalue(),
            raise_for_status=lambda: None,
        )
        with patch.object(news.httpx, "get", return_value=response) as get:
            content, media_type = news.fetch_article_image(
                "https://images.rappler.com/story-photo",
                publisher_url="https://www.rappler.com/news/story/?utm_source=feed",
            )
        self.assertEqual(content, source.getvalue())
        self.assertEqual(media_type, "image/jpeg")
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["Referer"], "https://www.rappler.com/news/story/")
        self.assertIn("Mozilla/5.0", headers["User-Agent"])

    def test_google_news_article_reuses_matching_direct_feed_image(self):
        google_url = "https://news.google.com/rss/articles/google-image-peer?oc=5"
        publisher_url = "https://newsinfo.inquirer.net/story"
        image_url = "https://newsinfo.inquirer.net/files/story-photo.jpg"
        google_article = {"id": "google-story", "url": google_url, "image": None}
        publisher_article = {
            "id": "publisher-story",
            "url": publisher_url,
            "image": image_url,
        }
        original_items = news._cache["items"]
        original_by_id = dict(news._by_id)
        try:
            news._cache["items"] = [google_article, publisher_article]
            news._by_id.clear()
            with (
                patch.object(
                    news, "_decode_google_news_urls",
                    return_value={google_url: publisher_url},
                ),
                patch.object(news, "_page_image") as page_image,
                patch.object(news, "sb", None),
            ):
                news._enrich_missing_images(news._cache["items"])
            self.assertEqual(google_article["image"], image_url)
            page_image.assert_not_called()
        finally:
            news._image_attempts.pop(google_url, None)
            news._cache["items"] = original_items
            news._by_id.clear()
            news._by_id.update(original_by_id)

    def test_image_enrichment_processes_past_the_first_batch(self):
        articles = [
            {
                "id": f"batch-{index}",
                "url": f"https://example.test/image-batch/{index}",
                "image": None,
            }
            for index in range(news._IMAGE_ENRICHMENT_BATCH_SIZE + 1)
        ]
        original_items = news._cache["items"]
        original_by_id = dict(news._by_id)

        def image_for(article):
            return f"https://www.rappler.com/images/{article['id']}.jpg"

        try:
            news._cache["items"] = articles
            news._by_id.clear()
            with (
                patch.object(news, "_decode_google_news_urls", return_value={}),
                patch.object(news, "_page_image", side_effect=image_for) as page_image,
                patch.object(news, "sb", None),
            ):
                news._enrich_missing_images(articles)
            self.assertEqual(page_image.call_count, len(articles))
            self.assertTrue(all(article["image"] for article in articles))
        finally:
            for article in articles:
                news._image_attempts.pop(article["url"], None)
            news._cache["items"] = original_items
            news._by_id.clear()
            news._by_id.update(original_by_id)

    def test_google_news_feed_keeps_the_publisher_as_story_source(self):
        response = SimpleNamespace(
            content=(
                b'<rss version="2.0"><channel><item>'
                b"<title>Local report</title>"
                b"<link>https://news.google.com/rss/articles/story-token</link>"
                b'<source url="https://publisher.example.test">Publisher News</source>'
                b"</item></channel></rss>"
            ),
            raise_for_status=lambda: None,
        )
        feed = {
            "url": "https://news.google.com/rss",
            "source": "Google News (Philippines)",
            "section": "national",
        }
        class AsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url):
                return response

        with patch.object(news.httpx, "AsyncClient", return_value=AsyncClient()), patch.object(
            news, "_image", return_value=None
        ):
            articles, error = asyncio.run(news._pull_feeds([feed]))[0]
        self.assertIsNone(error)
        self.assertEqual(articles[0]["source"], "Publisher News")

    def test_async_feed_retries_transient_timeouts_before_returning_articles(self):
        response = SimpleNamespace(
            content=(
                b'<rss version="2.0"><channel><item>'
                b"<title>Retried report</title>"
                b"<link>https://publisher.example.test/retried</link>"
                b"</item></channel></rss>"
            ),
            raise_for_status=lambda: None,
        )
        feed = {
            "url": "https://publisher.example.test/rss",
            "source": "Publisher News",
            "section": "national",
        }

        class AsyncClient:
            def __init__(self):
                self.attempts = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url):
                self.attempts += 1
                if self.attempts < 3:
                    raise httpx.TimeoutException("simulated timeout")
                return response

        client = AsyncClient()
        with (
            patch.object(news.httpx, "AsyncClient", return_value=client),
            patch.object(news, "_image", return_value=None),
            patch.dict("os.environ", {
                "NEWS_REQUEST_RETRIES": "2",
                "NEWS_RETRY_BACKOFF_SECONDS": "0",
            }),
        ):
            articles, error = asyncio.run(news._pull_feeds([feed]))[0]
        self.assertIsNone(error)
        self.assertEqual(client.attempts, 3)
        self.assertEqual(articles[0]["title"], "Retried report")

    def test_article_image_proxy_serves_publisher_photo(self):
        article = {"id": "article-photo", "image": "https://pna.gov.ph/photo.webp"}
        source = BytesIO()
        Image.new("RGB", (1600, 800), color=(40, 100, 180)).save(source, format="JPEG", quality=95)
        with patch.object(
            main.news, "get_article", return_value=article
        ), patch.object(
            main.news, "fetch_article_image", return_value=(source.getvalue(), "image/jpeg")
        ):
            response = main.article_image("article-photo", accept="image/webp")
        self.assertEqual(response.media_type, "image/webp")
        with Image.open(BytesIO(response.body)) as thumbnail:
            self.assertEqual(thumbnail.size, (960, 480))
        self.assertEqual(
            response.headers["cache-control"],
            "public, max-age=3600, stale-while-revalidate=86400",
        )
        self.assertEqual(response.headers["vary"], "Accept")

    def test_article_image_optimization_keeps_original_for_unsupported_clients(self):
        source = BytesIO()
        Image.new("RGB", (1200, 600), color=(120, 80, 40)).save(source, format="JPEG")
        original = source.getvalue()
        content, media_type = news.optimize_article_image(
            original, "image/jpeg", supports_webp=False
        )
        self.assertEqual(content, original)
        self.assertEqual(media_type, "image/jpeg")

    def test_article_image_optimization_preserves_avif_for_supported_browser(self):
        content, media_type = news.optimize_article_image(b"avif-data", "image/avif")
        self.assertEqual(content, b"avif-data")
        self.assertEqual(media_type, "image/avif")

    def test_background_image_enrichment_does_not_wait_for_publishers(self):
        entered = Event()
        release = Event()
        with patch.dict(news._cache, {"items": [{
            "id": "background-image",
            "url": "https://example.test/story",
            "image": None,
        }]}), patch.object(
            news,
            "_enrich_missing_images",
            side_effect=lambda items: (entered.set(), release.wait(2)),
        ):
            try:
                news._schedule_image_enrichment()
                self.assertTrue(entered.wait(1))
                self.assertFalse(release.is_set())
            finally:
                release.set()

    def test_article_image_proxy_rejects_unapproved_hosts(self):
        with patch.object(news.httpx, "get") as get:
            with self.assertRaises(ValueError):
                news.fetch_article_image("https://untrusted.example.test/photo.jpg")
        get.assert_not_called()

    def test_google_news_image_cdn_is_allowed_by_the_image_proxy(self):
        response = SimpleNamespace(
            is_redirect=False,
            headers={"content-type": "image/webp"},
            content=b"photo",
            raise_for_status=lambda: None,
        )
        with patch.object(news.httpx, "get", return_value=response):
            content, media_type = news.fetch_article_image(
                "https://lh3.googleusercontent.com/photo"
            )
        self.assertEqual(content, b"photo")
        self.assertEqual(media_type, "image/webp")

    def test_pna_photo_proxy_uses_the_working_publisher_image_host(self):
        response = SimpleNamespace(
            is_redirect=False,
            headers={"content-type": "image/webp"},
            content=b"photo",
            raise_for_status=lambda: None,
        )
        with patch.object(news.httpx, "get", return_value=response) as get:
            content, media_type = news.fetch_article_image(
                "https://pna.gov.ph/photo.webp"
            )
        self.assertEqual(content, b"photo")
        self.assertEqual(media_type, "image/webp")
        self.assertEqual(
            get.call_args.args[0], "https://www.pna.gov.ph/photo.webp"
        )

    def test_missing_article_images_are_enriched_in_cached_feed(self):
        article = {
            "id": "article-1", "url": "https://news.example.test/story",
            "image": None, "published": None,
        }
        original_cache_items = news._cache["items"]
        original_by_id = dict(news._by_id)
        with patch.object(news, "_page_image", return_value="https://cdn.example.test/cover.jpg"):
            try:
                news._publish([article])
                news._enrich_missing_images(news._cache["items"])
                self.assertEqual(news._cache["items"][0]["image"], "https://cdn.example.test/cover.jpg")
            finally:
                news._cache["items"] = original_cache_items
                news._by_id.clear()
                news._by_id.update(original_by_id)
                news._image_attempts.pop(article["url"], None)

    def test_publish_removes_reused_generic_feed_thumbnails(self):
        repeated_image = "https://images.example.test/publisher-logo.jpg"
        articles = [
            {"id": f"generic-{index}", "image": repeated_image, "published": None}
            for index in range(news._GENERIC_IMAGE_REUSE_LIMIT)
        ]
        articles.append({"id": "real-photo", "image": "https://images.example.test/real.jpg"})
        original_cache_items = news._cache["items"]
        original_by_id = dict(news._by_id)
        original_generic_images = news._generic_image_urls.copy()
        try:
            news._publish(articles)
            self.assertTrue(all(article["image"] is None for article in articles[:-1]))
            self.assertIsNone(news._usable_image(repeated_image))
            self.assertEqual(articles[-1]["image"], "https://images.example.test/real.jpg")
        finally:
            news._cache["items"] = original_cache_items
            news._by_id.clear()
            news._by_id.update(original_by_id)
            news._generic_image_urls.clear()
            news._generic_image_urls.update(original_generic_images)

    def test_story_detail_fetches_missing_image_metadata_on_demand(self):
        article = {
            "id": "article-detail-image", "url": "https://news.example.test/detail",
            "image": None,
        }
        original_article = news._by_id.get(article["id"])
        original_attempt = news._image_attempts.get(article["url"])
        news._by_id[article["id"]] = article
        news._image_attempts.pop(article["url"], None)
        try:
            with patch.object(
                news, "_page_image", return_value="https://cdn.example.test/detail.jpg"
            ):
                result = news.get_article(article["id"])
            if result is None:
                self.fail("Expected the article to be returned")
            self.assertEqual(result["image"], "https://cdn.example.test/detail.jpg")
        finally:
            if original_article is None:
                news._by_id.pop(article["id"], None)
            else:
                news._by_id[article["id"]] = original_article
            if original_attempt is None:
                news._image_attempts.pop(article["url"], None)
            else:
                news._image_attempts[article["url"]] = original_attempt

    def test_missing_article_with_empty_supabase_response_returns_not_found(self):
        supabase = MagicMock()
        query = supabase.table.return_value.select.return_value.eq.return_value
        query.maybe_single.return_value.execute.return_value = None

        with (
            patch.object(news, "sb", supabase),
            patch.object(news, "start_refresh_background") as refresh,
        ):
            result = news.get_article("missing-article-empty-response")

        self.assertIsNone(result)
        refresh.assert_called_once()

    def test_preprocessing_lemmatizes_and_filters_stop_words(self):
        class Token:
            def __init__(self, lemma, is_alpha=True, is_stop=False):
                self.lemma_ = lemma
                self.is_alpha = is_alpha
                self.is_stop = is_stop

        with patch.object(intelligence, "_nlp", return_value=lambda _: [
            Token("report"), Token("the", is_stop=True), Token("123", is_alpha=False)
        ]):
            self.assertEqual(intelligence.preprocess_text("Reports the 123"), ["report"])

    def test_named_entity_extraction_groups_spacy_entity_labels(self):
        class Entity:
            def __init__(self, text, label):
                self.text = text
                self.label_ = label

        class Doc:
            ents = [Entity("Mira Santos", "PERSON"), Entity("Manila", "GPE"),
                    Entity("April 2025", "DATE"), Entity("News Lab", "ORG")]

        with patch.object(intelligence, "_nlp", return_value=lambda _: Doc()):
            result = intelligence.extract_entities("sample article")
        self.assertEqual(result["people"], ["Mira Santos"])
        self.assertEqual(result["locations"], ["Manila"])
        self.assertEqual(result["dates"], ["April 2025"])
        self.assertEqual(result["organizations"], ["News Lab"])

    def test_vader_sentiment_labels_positive_negative_and_neutral(self):
        self.assertEqual(intelligence.sentiment("A wonderful success and a great result.")["label"], "positive")
        self.assertEqual(intelligence.sentiment("A terrible failure with awful consequences.")["label"], "negative")
        self.assertEqual(intelligence.sentiment("The meeting is scheduled for Tuesday.")["label"], "neutral")

    def test_tfidf_extracts_distinctive_terms_by_article(self):
        docs = [
            {"id": "a", "title": "Climate climate research", "summary": "Ocean warming study"},
            {"id": "b", "title": "Football tournament", "summary": "League championship match"},
        ]
        result = intelligence.tfidf_keywords(docs, top_k=5)
        self.assertEqual(set(result), {"a", "b"})
        self.assertIn("climate", {item["term"] for item in result["a"]})
        self.assertIn("football", {item["term"] for item in result["b"]})

    def test_hybrid_search_combines_bm25_and_cosine_similarity(self):
        docs = [
            {"id": "climate", "title": "Climate research", "summary": "Warming ocean study"},
            {"id": "sports", "title": "Football league", "summary": "Championship match"},
        ]
        with (
            patch.object(intelligence, "sb", None),
            patch.object(intelligence, "_encode_query", return_value=np.array([1.0, 0.0])),
            patch.object(intelligence, "_encode_articles",
                         return_value=(np.array([[1.0, 0.0], [0.0, 1.0]]), [])),
        ):
            ranked, mode = intelligence.hybrid_search("climate ocean", docs, limit=1)
        self.assertEqual(mode, "bm25+sentence-transformers")
        self.assertEqual(ranked[0]["id"], "climate")

    def test_hybrid_search_finds_paraphrases_without_keyword_overlap(self):
        docs = [
            {"id": "harvest", "title": "El Niño cuts harvest as water shortages threaten growers"},
            {"id": "sports", "title": "Football league opens championship season"},
        ]
        with (
            patch.object(intelligence, "sb", None),
            patch.object(intelligence, "_encode_query", return_value=np.array([1.0, 0.0])),
            patch.object(
                intelligence,
                "_encode_articles",
                return_value=(np.array([[1.0, 0.0], [0.0, 1.0]]), []),
            ),
        ):
            ranked, _ = intelligence.hybrid_search("Why are food prices rising?", docs, limit=1)

        self.assertEqual([article["id"] for article in ranked], ["harvest"])

    def test_hybrid_search_can_skip_remote_vector_store(self):
        docs = [{"id": "climate", "title": "Climate research", "summary": "Warming ocean study"}]
        supabase = MagicMock()
        with (
            patch.object(intelligence, "sb", supabase),
            patch.object(intelligence, "_encode_query", return_value=np.array([1.0, 0.0])),
            patch.object(
                intelligence,
                "_encode_articles",
                return_value=(np.array([[1.0, 0.0]]), []),
            ),
        ):
            ranked, mode = intelligence.hybrid_search(
                "climate change", docs, limit=1, use_vector_store=False,
            )

        self.assertEqual([article["id"] for article in ranked], ["climate"])
        self.assertEqual(mode, "bm25+sentence-transformers")
        supabase.table.assert_not_called()
        supabase.rpc.assert_not_called()

    def test_article_search_text_includes_content_topics_events_issues_and_people(self):
        article = {
            "title": "Public inquiry opens",
            "description": "A national report examines the inquiry.",
            "content": [{"value": "Officials discuss the water contamination incident."}],
            "topics": ["Public health"],
            "events": ["Water contamination"],
            "issues": ["Drinking water safety"],
            "author": "Mira Santos",
            "category": "Investigations",
        }

        text = intelligence._article_text(article)

        for value in (
            "Public inquiry opens", "national report", "water contamination incident",
            "Public health", "Water contamination", "Drinking water safety",
            "Mira Santos", "Investigations",
        ):
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_search_discovery_uses_hybrid_search_and_indexes_article_metadata(self):
        archived = {
            "id": "water-safety",
            "title": "Inquiry opens after community illness reports",
            "summary": "Officials investigate a water contamination event.",
            "source": "Rappler",
            "section": "national",
            "url": "https://example.test/water-safety",
            "published": "2024-01-01T00:00:00Z",
            "author": "Mira Santos",
            "category": "Public health",
            "topics": ["Public health"],
            "content": "Residents say the drinking water made them sick.",
        }
        with (
            patch.dict(news._cache, {"items": [archived], "stored_loaded": True}),
            patch.dict(news._by_id, {}, clear=True),
            patch.dict(news._search_cache, {}, clear=True),
            patch.object(news, "sb", None),
            patch.object(news, "_schedule_image_enrichment"),
            patch.object(
                news,
                "_pull_feeds",
                new=AsyncMock(return_value=[([], "Feed returned no entries")]),
            ),
            patch.object(news, "fast_search", return_value=([], None)),
            patch.object(
                news,
                "hybrid_search",
                return_value=([archived], "bm25+sentence-transformers"),
            ) as semantic_search,
            patch.object(news, "media_search_text", return_value="Rappler news source"),
        ):
            result = news.search_discovery("Why did residents get sick?", period="historical")

        self.assertEqual([article["id"] for article in result["articles"]], ["water-safety"])
        self.assertEqual(result["mode"], "archive+live-rss+bm25+sentence-transformers")
        indexed_article = semantic_search.call_args.args[1][0]
        self.assertEqual(indexed_article["search_metadata"], "Rappler news source")
        self.assertIn("drinking water made them sick", intelligence._article_text(indexed_article))
        self.assertFalse(semantic_search.call_args.kwargs["use_vector_store"])

    def test_fast_search_corrects_misspelled_terms_without_loading_embeddings(self):
        docs = [
            {"id": "farm", "title": "Agriculture researchers study crop harvests"},
            {"id": "sports", "title": "Basketball league opens championship season"},
        ]
        with patch.object(intelligence, "_encode_query", side_effect=AssertionError):
            ranked, corrected = intelligence.fast_search("agricultre", docs, limit=1)
        self.assertEqual([article["id"] for article in ranked], ["farm"])
        self.assertEqual(corrected, "agriculture")
        no_match, no_correction = intelligence.fast_search(
            "qzxwvv nonsenseword", docs, limit=5
        )
        self.assertEqual(no_match, [])
        self.assertIsNone(no_correction)

    def test_fast_search_matches_hyphenated_search_to_separate_words(self):
        docs = [
            {"id": "agri-ignite", "title": "Agri Ignite Year 2 supports local farmers"},
            {"id": "unrelated", "title": "Basketball league opens championship season"},
        ]

        ranked, _ = intelligence.fast_search("agri-ignite year 2", docs, limit=1)

        self.assertEqual([article["id"] for article in ranked], ["agri-ignite"])

    def test_content_recommendations_rank_by_interest_similarity(self):
        docs = [
            {"id": "climate", "title": "Climate research", "summary": "Warming ocean study"},
            {"id": "sports", "title": "Football league", "summary": "Championship match"},
        ]
        with (
            patch.object(intelligence, "sb", None),
            patch.object(intelligence, "_encode_query", return_value=np.array([1.0, 0.0])),
            patch.object(intelligence, "_encode_articles",
                         return_value=(np.array([[1.0, 0.0], [0.0, 1.0]]), [])),
        ):
            ranked = intelligence.content_recommendations(docs, ["climate science"], limit=1)
        self.assertEqual(ranked[0]["id"], "climate")

    def test_content_recommendations_do_not_load_sentence_transformer(self):
        docs = [
            {"id": "climate", "title": "Climate research", "summary": "Warming ocean study"},
            {"id": "sports", "title": "Football league", "summary": "Championship match"},
        ]
        with patch.object(intelligence, "_embedding_model", side_effect=AssertionError):
            ranked = intelligence.content_recommendations(docs, ["climate science"], limit=1)
        self.assertEqual(ranked[0]["id"], "climate")

    def test_content_recommendations_use_reading_history(self):
        docs = [
            {"id": "climate", "title": "Climate research", "summary": "Warming ocean study"},
            {"id": "sports", "title": "Football match championship", "summary": "League players won"},
        ]
        ranked = intelligence.content_recommendations(
            docs, [], limit=1, history=[{"title": "Football match championship"}]
        )
        self.assertEqual(ranked[0]["id"], "sports")

    def test_feed_listing_serves_cache_without_waiting_for_refresh(self):
        cached_items = [
            {"id": "one", "section": "national", "title": "Cached story", "summary": ""},
            {"id": "two", "section": "local", "title": "Other cached story", "summary": ""},
        ]
        original_items = news._cache["items"]
        original_at = news._cache["at"]
        try:
            news._cache.update(items=cached_items, at=1)
            with patch.object(news, "start_refresh_background") as start_refresh:
                result = news.list_articles("national", None, None)
            self.assertEqual([item["id"] for item in result], ["one"])
            start_refresh.assert_called_once_with(section="national")
        finally:
            news._cache.update(items=original_items, at=original_at)

    def test_feed_listing_does_not_block_on_stored_cache_load(self):
        original_items = news._cache["items"]
        original_at = news._cache["at"]
        original_stored_loaded = news._cache["stored_loaded"]
        original_by_id = dict(news._by_id)
        try:
            news._cache.update(items=[], at=0.0, stored_loaded=False)
            with (
                patch.object(news, "sb", object()),
                patch.object(news, "_load_stored_articles", side_effect=AssertionError),
                patch.object(news, "start_refresh_background") as start_refresh,
            ):
                result = news.list_articles("national", None, None)
            self.assertEqual(result, [])
            start_refresh.assert_called_once_with(section="national")
        finally:
            news._cache.update(items=original_items, at=original_at, stored_loaded=original_stored_loaded)
            news._by_id.clear()
            news._by_id.update(original_by_id)

    def test_empty_stored_cache_is_not_reloaded_on_each_dashboard_request(self):
        original_stored_loaded = news._cache["stored_loaded"]
        try:
            news._cache.update(stored_loaded=False)
            with (
                patch.object(news, "sb", object()),
                patch.object(news, "_load_stored_articles", return_value=[]) as load_stored,
            ):
                news._load_stored_once()
                news._load_stored_once()
            load_stored.assert_called_once_with()
        finally:
            news._cache.update(stored_loaded=original_stored_loaded)

    def test_stored_articles_are_checked_for_missing_images_when_loaded(self):
        original_items = news._cache["items"]
        original_at = news._cache["at"]
        original_stored_loaded = news._cache["stored_loaded"]
        original_by_id = dict(news._by_id)
        stored_article = {
            "id": "article-without-image",
            "url": "https://news.google.com/rss/articles/article-token",
            "image": None,
            "section": "local",
            "published": None,
        }
        try:
            news._cache.update(items=[], at=0.0, stored_loaded=False)
            news._by_id.clear()
            with (
                patch.object(news, "sb", object()),
                patch.object(news, "_load_stored_articles", return_value=[stored_article]),
                patch.object(news, "_schedule_image_enrichment") as enrich,
            ):
                news._load_stored_once()
            enrich.assert_called_once_with()
        finally:
            news._cache.update(
                items=original_items, at=original_at, stored_loaded=original_stored_loaded
            )
            news._by_id.clear()
            news._by_id.update(original_by_id)

    def test_partial_feed_failure_keeps_cached_articles_and_publishes_successes(self):
        old_items = news._cache["items"]
        old_at = news._cache["at"]
        old_stored_loaded = news._cache["stored_loaded"]
        old_last_sync = news._cache["last_successful_sync"]
        old_sync_by_section = dict(news._cache["last_successful_sync_by_section"])
        old_last_refresh = news._cache.get("last_refresh")
        old_by_id = dict(news._by_id)
        old_attempts = dict(news._last_attempt_by_section)
        cached = {
            "id": "cached", "title": "Cached report", "summary": "",
            "source": "Existing", "section": "national",
            "url": "https://example.test/cached",
        }
        fresh = {
            "id": "fresh", "title": "Fresh report", "summary": "",
            "source": "Available source", "section": "local",
            "url": "https://example.test/fresh",
            "canonical_url": "https://example.test/fresh",
            "published": None, "image_url": None,
        }

        async def pull(_feeds):
            return [([fresh], None), ([], "source unavailable")]

        try:
            news._cache.update(
                items=[cached], at=0.0, stored_loaded=True,
                last_successful_sync=None, last_successful_sync_by_section={},
            )
            news._by_id.clear()
            news._by_id.update({"cached": cached})
            with (
                patch.object(news, "sb", None),
                patch.object(news, "_load_stored_once"),
                patch.object(news, "_due_feeds", return_value=news.FEEDS[:2]),
                patch.object(news, "_pull_feeds", side_effect=pull),
                patch.object(news, "_enrich_missing_images"),
            ):
                result = news._refresh_now(force=True)
            self.assertEqual({article["id"] for article in result}, {"cached", "fresh"})
            self.assertIsNotNone(news._cache["last_successful_sync"])
            self.assertEqual(news._cache["last_refresh"]["failed_feeds"][0]["error"], "source unavailable")
        finally:
            news._cache.update(
                items=old_items, at=old_at, stored_loaded=old_stored_loaded,
                last_successful_sync=old_last_sync,
                last_successful_sync_by_section=old_sync_by_section,
                last_refresh=old_last_refresh,
            )
            news._by_id.clear()
            news._by_id.update(old_by_id)
            news._last_attempt_by_section.clear()
            news._last_attempt_by_section.update(old_attempts)

    def test_all_empty_or_failed_feeds_do_not_replace_cached_articles(self):
        old_items = news._cache["items"]
        old_at = news._cache["at"]
        old_stored_loaded = news._cache["stored_loaded"]
        old_last_refresh = news._cache.get("last_refresh")
        old_by_id = dict(news._by_id)
        old_attempts = dict(news._last_attempt_by_section)
        cached = {
            "id": "cached", "title": "Cached report", "summary": "",
            "source": "Existing", "section": "national",
            "url": "https://example.test/cached",
        }

        async def pull(_feeds):
            return [([], "empty or unavailable")]

        try:
            news._cache.update(items=[cached], at=0.0, stored_loaded=True)
            news._by_id.clear()
            news._by_id.update({"cached": cached})
            with (
                patch.object(news, "sb", None),
                patch.object(news, "_load_stored_once"),
                patch.object(news, "_due_feeds", return_value=news.FEEDS[:1]),
                patch.object(news, "_pull_feeds", side_effect=pull),
                patch.object(news, "_enrich_missing_images"),
            ):
                result = news._refresh_now(force=True)
            self.assertEqual([article["id"] for article in result], ["cached"])
            self.assertEqual(news._cache["last_refresh"]["collected"], 0)
        finally:
            news._cache.update(
                items=old_items, at=old_at, stored_loaded=old_stored_loaded,
                last_refresh=old_last_refresh,
            )
            news._by_id.clear()
            news._by_id.update(old_by_id)
            news._last_attempt_by_section.clear()
            news._last_attempt_by_section.update(old_attempts)

    def test_articles_api_reports_background_refresh_state(self):
        with (
            patch.object(main.news, "list_articles", return_value=[{"id": "cached"}]),
            patch.object(main.news, "count_articles", return_value=1),
            patch.object(main.news, "is_refreshing", return_value=True),
            patch.object(main.news, "is_image_enrichment_running", return_value=True),
            patch.object(main.news, "refresh_status", return_value={"last_successful_sync": None}),
        ):
            result = main.articles("national", None, None, None, limit=10, offset=0)
        self.assertEqual(result, {
            "articles": [{"id": "cached"}],
            "total": 1,
            "next_offset": None,
            "refreshing": True,
            "image_enrichment_running": True,
            "last_successful_sync": None,
        })

    def test_category_filters_return_matching_stories_with_requested_batch_size(self):
        docs = [
            {"id": "business", "title": "Local business expands", "summary": "", "section": "national"},
            {"id": "agriculture", "title": "Farmers celebrate new harvest", "summary": "", "section": "local"},
            {"id": "sports", "title": "Volleyball league opens", "summary": "", "section": "national"},
        ]
        original_items = news._cache["items"]
        original_at = news._cache["at"]
        try:
            news._cache.update(items=docs, at=1)
            with patch.object(news, "start_refresh_background"):
                result = news.list_articles(None, None, "Agriculture", limit=1000)
            self.assertEqual([article["id"] for article in result], ["agriculture"])
        finally:
            news._cache.update(items=original_items, at=original_at)

    def test_category_filters_exclude_incidental_mentions_across_sections(self):
        docs = [
            {
                "id": "sports-national",
                "title": "Basketball league opens its championship season",
                "summary": "Health officials inspect the arena before the first game.",
                "section": "national",
            },
            {
                "id": "politics-regional",
                "title": "Protesters rally over proposed election law",
                "summary": "The market near the government building is closed.",
                "section": "regional",
            },
            {
                "id": "health-local",
                "title": "Hospital opens a new community clinic",
                "summary": "Doctors will provide medical care to local patients.",
                "section": "local",
            },
            {
                "id": "business-international",
                "title": "Company reports higher quarterly earnings",
                "summary": "The financial group cites revenue growth.",
                "section": "international",
            },
            {
                "id": "bank-robbery-national",
                "title": "Police arrest suspects after bank robbery",
                "summary": "Investigators say the theft occurred overnight.",
                "section": "national",
            },
        ]
        original_items = news._cache["items"]
        original_at = news._cache["at"]
        try:
            news._cache.update(items=docs, at=1)
            with patch.object(news, "start_refresh_background"):
                health = news.list_articles("national", None, "Health", limit=100)
                sports = news.list_articles("national", None, "Sports", limit=100)
                politics = news.list_articles("regional", None, "Politics", limit=100)
                business = news.list_articles("international", None, "Business", limit=100)
                crime = news.list_articles("national", None, "Crime & Safety", limit=100)

            self.assertEqual([article["id"] for article in health], [])
            self.assertEqual([article["id"] for article in sports], ["sports-national"])
            self.assertEqual([article["id"] for article in politics], ["politics-regional"])
            self.assertEqual([article["id"] for article in business], ["business-international"])
            self.assertEqual([article["id"] for article in crime], ["bank-robbery-national"])
            self.assertEqual(news.count_articles("national", "Health"), len(health))
            self.assertEqual(news.count_articles("regional", "Sports"), 0)
            self.assertEqual(news.count_articles("local", "Health"), 1)
        finally:
            news._cache.update(items=original_items, at=original_at)

    def test_topic_classifier_chooses_one_primary_topic_and_rejects_keyword_collisions(self):
        examples = [
            (
                "Sports",
                "NCAA: EAC honors past pioneers after ending Final Four drought",
                "The basketball team secured its first-ever semifinal berth.",
            ),
            (
                "Business",
                "Company reports higher quarterly earnings",
                "Revenue and profit increased, the company said.",
            ),
            (
                "Agriculture",
                "Farmers expand rice harvest",
                "The agriculture office expects higher crop yields.",
            ),
            (
                "Politics",
                "Ridon: December verdict possible as VP defense nears final witnesses",
                "Vice President Sara Duterte's impeachment trial is before the Senate.",
            ),
            (
                "Health",
                "Hospital opens community clinic",
                "Doctors will provide medical care to local patients.",
            ),
            (
                "Technology",
                "It's game over for Jensen Huang, king of AI chips",
                "The Nvidia executive faces an AI industry shake-up. A Nations League match is also mentioned.",
            ),
            (
                "Education",
                "School board approves new curriculum",
                "Teachers and students will begin classes next semester.",
            ),
            (
                "Environment",
                "Climate change worsens flooding in coastal towns",
                "Rising temperatures and emissions are putting ecosystems at risk.",
            ),
            (
                "Entertainment",
                "'Taylor Swift of games': Grand Theft Auto is back after a 13-year wait",
                "The gaming phenomenon is the most expensive video game ever developed.",
            ),
            (
                "Crime & Safety",
                "Police arrest suspect after robbery",
                "Investigators recovered stolen property from the suspect.",
            ),
            (
                "Politics",
                "US judge blocks Trump's plan to renovate historic DC golf course",
                "The federal court halted the president's plan for a championship-level course.",
            ),
            (
                "Politics",
                "US Democrats flip Alaska Senate seat as Mary Peltola wins race",
                "The final outstanding midterm election race was won by a Senate candidate.",
            ),
            (
                "Education",
                "Is China's dark tourism turning disaster education into entertainment?",
                "The report examines how people learn about disasters through tourism.",
            ),
        ]
        for expected, title, summary in examples:
            with self.subTest(title=title):
                self.assertEqual(news._classify_article_topics(title, summary), [expected])

        self.assertEqual(
            news._classify_article_topics(
                "P512-M Ultra Lotto jackpot not won",
                "The game's top prize remains without a winner.",
            ),
            [],
        )

    def test_articles_api_forwards_category_and_pagination(self):
        page = [{"id": f"sports-{index}"} for index in range(21)]
        with (
            patch.object(main.news, "list_articles", return_value=page) as list_articles,
            patch.object(main.news, "count_articles", return_value=30),
            patch.object(main.news, "is_refreshing", return_value=False),
        ):
            result = main.articles(None, None, "Sports", None, limit=20, offset=20)
        self.assertEqual(len(result["articles"]), 20)
        self.assertEqual(result["next_offset"], 40)
        list_articles.assert_called_once_with(
            None, None, "Sports", limit=21, offset=20, interests=[]
        )

    def test_search_endpoint_delegates_to_news_discovery(self):
        response = {
            "articles": [{"id": "farm", "title": "Agriculture researchers report crop losses"}],
            "corrected_query": "agriculture",
            "mode": "archive+live-rss+bm25",
        }
        with patch.object(main.news, "search_discovery", return_value=response) as search:
            result = main.search_articles("agricultre", limit=10, offset=0, uid=None)
        self.assertEqual(result["corrected_query"], "agriculture")
        self.assertEqual(result["mode"], "archive+live-rss+bm25")
        self.assertEqual(search.call_args.kwargs["scope"], "all")
        self.assertEqual(search.call_args.kwargs["period"], "all")

    def test_search_endpoint_returns_a_service_error_when_semantic_search_is_unavailable(self):
        with patch.object(
            main.news,
            "search_discovery",
            side_effect=intelligence.IntelligenceUnavailable("Search model unavailable."),
        ):
            with self.assertRaises(main.HTTPException) as raised:
                main.search_articles(q="agri-ignite", limit=10, offset=0, uid=None)

        self.assertEqual(raised.exception.status_code, 503)

    def test_search_endpoint_applies_geographic_and_topic_filters_and_pagination(self):
        docs = [
            {"id": "local-farm", "section": "local", "title": "Farmers grow rice"},
            {"id": "world-farm", "section": "international", "title": "Farmers grow rice"},
        ]
        response = {"articles": [docs[0]], "next_offset": None}
        with patch.object(main.news, "search_discovery", return_value=response) as search:
            result = main.search_articles(
                "farmers", section="local", topic="Agriculture",
                limit=1, offset=0, uid=None,
            )
        self.assertEqual(result["articles"], [docs[0]])
        self.assertIsNone(result["next_offset"])
        self.assertEqual(search.call_args.kwargs["section"], "local")
        self.assertEqual(search.call_args.kwargs["topic"], "Agriculture")

    def test_dashboard_prioritizes_local_trending_and_paginates_latest(self):
        docs = [
            {"id": "world", "section": "international", "published": "2025-01-03T00:00:00Z"},
            {"id": "national", "section": "national", "published": "2025-01-02T00:00:00Z"},
            {"id": "local", "section": "local", "published": "2025-01-01T00:00:00Z"},
        ]
        with (
            patch.object(main.news, "list_articles", side_effect=[
                docs,
                [{"id": "local"}, {"id": "national"}, {"id": "world"}],
                docs[:2],
            ]),
            patch.object(main.news, "count_articles", return_value=3),
            patch.object(main.news, "is_refreshing", return_value=False),
        ):
            result = main.dashboard(limit=2, offset=0, uid=None)
        self.assertEqual([item["id"] for item in result["trending"]], ["local", "national"])
        self.assertEqual([item["id"] for item in result["latest"]], ["world", "national"])
        self.assertEqual(result["next_offset"], 2)
        self.assertFalse(result["has_activity"])

        with (
            patch.object(main.news, "list_articles", side_effect=[
                docs,
                [{"id": "local"}],
                docs[2:],
            ]),
            patch.object(main.news, "count_articles", return_value=3),
            patch.object(main.news, "is_refreshing", return_value=False),
        ):
            next_page = main.dashboard(limit=2, offset=2, uid=None)
        self.assertEqual([item["id"] for item in next_page["latest"]], ["local"])
        self.assertEqual([item["id"] for item in next_page["trending"]], ["local"])
        self.assertIsNone(next_page["next_offset"])

    def test_dashboard_prioritizes_local_regional_national_and_international(self):
        docs = [
            {"id": "world", "section": "international", "published": "2025-01-04"},
            {"id": "national", "section": "national", "published": "2025-01-03"},
            {"id": "regional", "section": "regional", "published": "2025-01-02"},
            {"id": "local", "section": "local", "published": "2025-01-01"},
        ]
        with (
            patch.object(main.news, "list_articles", side_effect=[docs, docs, docs]),
            patch.object(main.news, "count_articles", return_value=len(docs)),
            patch.object(main.news, "is_refreshing", return_value=False),
        ):
            result = main.dashboard(limit=10, offset=0, uid=None)
        self.assertEqual(
            [item["id"] for item in result["trending"]],
            ["local", "regional", "national", "world"],
        )

    def test_news_feeds_provide_separate_caraga_and_mindanao_sections(self):
        caraga = next(feed for feed in feeds.FEEDS if feed["source"] == "Google News (Caraga)")
        mindanao = next(feed for feed in feeds.FEEDS if feed["source"] == "Google News (Mindanao)")
        self.assertEqual(caraga["section"], "local")
        self.assertEqual(mindanao["section"], "regional")

    def test_dashboard_returns_all_feed_items_and_all_news_state_without_activity(self):
        docs = [
            {"id": f"story-{index}", "section": "national", "published": f"2025-01-{index + 1:02d}"}
            for index in range(12)
        ]
        with (
            patch.object(main.news, "list_articles", side_effect=[docs, docs, docs]),
            patch.object(main.news, "count_articles", return_value=len(docs)),
            patch.object(main.news, "is_refreshing", return_value=False),
        ):
            result = main.dashboard(limit=1000, offset=0, uid=None)
        self.assertEqual(len(result["trending"]), len(docs))
        self.assertEqual(len(result["latest"]), len(docs))
        self.assertEqual(result["recommended"], [])
        self.assertFalse(result["has_activity"])

    def test_compare_coverage_returns_other_source_reports(self):
        original = {"id": "story", "title": "Climate report", "source": "Source A"}
        related = [
            {"id": "same-source", "source": "Source A"},
            {"id": "other-source", "source": "Source B", "url": "https://example.test/report"},
        ]
        with (
            patch.object(main.news, "get_article", return_value=original),
            patch.object(main.news, "list_articles", return_value=[original, *related]),
            patch.object(intelligence, "content_recommendations", return_value=[original, *related]),
        ):
            result = main.compare_coverage("story", limit=5)
        self.assertEqual([report["id"] for report in result["reports"]], ["other-source"])
        self.assertEqual(result["reports"][0]["url"], "https://example.test/report")

    def test_cold_feed_listing_returns_while_refresh_runs_in_background(self):
        started = Event()
        release = Event()
        finished = Event()
        original_items = news._cache["items"]
        original_at = news._cache["at"]
        original_by_id = dict(news._by_id)
        with news._refresh_state_lock:
            original_refreshing = news._refreshing
            news._refreshing = False
        news._cache.update(items=[], at=0.0)

        def delayed_refresh(force=False, section=None):
            started.set()
            release.wait(timeout=2)
            news._publish([{
                "id": "fresh", "section": "national", "title": "Fresh story",
                "summary": "", "url": "https://example.test/fresh", "published": None,
            }])
            finished.set()
            return news._cache["items"]

        try:
            with (
                patch.object(news, "sb", None),
                patch.object(news, "_refresh_now", side_effect=delayed_refresh),
            ):
                start = monotonic()
                self.assertEqual(news.list_articles("national", None, None), [])
                self.assertLess(monotonic() - start, 0.5)
                self.assertTrue(started.wait(timeout=1))
                self.assertTrue(news.is_refreshing())
                release.set()
                self.assertTrue(finished.wait(timeout=1))
                deadline = monotonic() + 1
                while news.is_refreshing() and monotonic() < deadline:
                    sleep(0.01)
                self.assertEqual(news.list_articles("national", None, None)[0]["id"], "fresh")
        finally:
            release.set()
            with news._refresh_state_lock:
                news._refreshing = original_refreshing
            news._cache.update(items=original_items, at=original_at)
            news._by_id.clear()
            news._by_id.update(original_by_id)

    def test_news_feed_search_uses_fast_typo_tolerant_retrieval(self):
        docs = [{"id": "climate", "title": "Climate report"}]
        original_items = news._cache["items"]
        original_at = news._cache["at"]
        try:
            news._cache.update(items=docs, at=1)
            with (
                patch.object(news, "start_refresh_background"),
                patch.object(news, "fast_search", return_value=(docs, None)),
            ):
                result = news.list_articles(None, "climate", None)
            self.assertEqual(result, docs)
        finally:
            news._cache.update(items=original_items, at=original_at)

    def test_lda_and_kmeans_produce_article_groups(self):
        docs = articles_for_topics()
        result = intelligence.discover_topics(docs, topic_count=3)
        self.assertEqual(len(result["topics"]), 3)
        self.assertIn("lda_perplexity", result["evaluation"])
        self.assertIn("kmeans_silhouette", result["evaluation"])
        grouped = [article_id for cluster in result["clusters"] for article_id in cluster["article_ids"]]
        self.assertCountEqual(grouped, [article["id"] for article in docs])

    def test_classifiers_report_metrics_and_predictions_for_labeled_articles(self):
        labels = ["climate", "sports", "health"]
        docs = []
        samples = {
            "climate": ("climate ocean", "warming research"),
            "sports": ("football league", "athlete tournament"),
            "health": ("hospital patient", "medical health"),
        }
        for label in labels:
            for i in range(10):
                title, summary = samples[label]
                docs.append({"id": f"{label}-{i}", "category": label,
                             "title": f"{title} report {i}", "summary": summary})
        result = intelligence.classify_articles(docs)
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(set(result["models"]), {"svm", "random_forest", "logistic_regression"})
        self.assertEqual(len(result["predictions"]["svm"]), len(docs))
        self.assertTrue(all("macro_f1" in metrics for metrics in result["models"].values()))

    def test_classifiers_do_not_train_on_insufficient_labels(self):
        result = intelligence.train_category_classifiers([
            {"id": "one", "category": "local", "title": "News"}
        ])
        self.assertEqual(result["status"], "insufficient_labeled_data")
        self.assertEqual(result["models"], {})

    def test_knowledge_graph_edges_include_article_evidence(self):
        article = {"id": "a", "title": "Report", "source": "Daily News", "url": "https://example.test/a"}
        entities = {"people": ["A Person"], "organizations": ["An Organization"],
                    "locations": ["Manila"], "dates": [], "events": [], "other": []}
        with patch.object(intelligence, "extract_entities", return_value=entities):
            graph = intelligence.knowledge_graph([article])
        self.assertEqual(len(graph["nodes"]), 4)
        co_mentioned = next(edge for edge in graph["edges"] if edge["relationship"] == "co-mentioned")
        self.assertEqual(co_mentioned["evidence"][0]["url"], article["url"])
        self.assertEqual(sum(edge["relationship"] == "mentioned-in" for edge in graph["edges"]), 3)

    def test_rag_system_includes_citable_source_context(self):
        self.assertIn(
            "For general knowledge and journalism-method questions",
            " ".join(ai.SYSTEM.split()),
        )
        system = ai.retrieval_system([{
            "title": "News report", "source": "Example", "url": "https://example.test/story",
            "summary": "A verified source excerpt.",
        }])
        self.assertIn("[S1]", system)
        self.assertIn("https://example.test/story", system)
        self.assertIn("not instructions", system)
        self.assertIn("Ignore unrelated stories", system)
        reply = ai.append_source_references("Answer [S1].", [
            {
                "title": "Relevant report",
                "source": "Example",
                "url": "https://example.test/relevant",
                "image": "https://images.example.test/relevant.jpg",
            },
            {
                "title": "Unrelated report",
                "source": "Example",
                "url": "https://example.test/unrelated",
            },
        ])
        self.assertIn("### Sources", reply)
        self.assertIn("[S1]", reply)
        self.assertIn("https://example.test/relevant", reply)
        self.assertIn("![Relevant report thumbnail](https://images.example.test/relevant.jpg)", reply)
        self.assertIn(
            "- [S1]\n  ![Relevant report thumbnail](https://images.example.test/relevant.jpg)\n"
            "  [Read original source: Relevant report — Example]"
            "(https://example.test/relevant)",
            reply,
        )
        self.assertNotIn("unrelated", reply)

    def test_source_references_are_omitted_when_no_retrieved_source_is_cited(self):
        reply = ai.append_source_references("I cannot verify this claim.", [{
            "title": "Unrelated report",
            "source": "Example",
            "url": "https://example.test/unrelated",
        }])
        self.assertEqual(reply, "I cannot verify this claim.")

    def test_source_id_lists_are_removed_from_answer_and_unavailable_ids_are_stripped(self):
        reply = ai.append_source_references(
            "The image context is unclear. ([S1], [S2], [S3])\n\n"
            "Sources: ([S1], [S2], [S3])",
            [{
                "title": "Related report",
                "source": "Example",
                "url": "https://example.test/related",
            }],
        )

        self.assertNotIn("([S1], [S2], [S3])", reply)
        self.assertNotIn("[S2]", reply)
        self.assertNotIn("[S3]", reply)
        self.assertIn("Related report", reply)

    def test_research_filters_topic_location_and_requested_date(self):
        today = datetime.now(timezone.utc)
        recent_sports = {
            "id": "recent-sports",
            "title": "National basketball league opens finals",
            "summary": "Teams begin the championship series.",
            "section": "national",
            "category": "Sports",
            "topics": ["basketball"],
            "published": (today - timedelta(hours=2)).isoformat(),
        }
        outdated_sports = {
            **recent_sports,
            "id": "outdated-sports",
            "published": (today - timedelta(days=20)).isoformat(),
        }
        international_sports = {
            **recent_sports,
            "id": "international-sports",
            "section": "international",
        }
        start, end = main._requested_date_window("top sports today", trending=True)

        self.assertTrue(main._matches_research_filters(
            recent_sports, topic="sports", section=None,
            philippines_only=True, start=start, end=end,
        ))
        self.assertFalse(main._matches_research_filters(
            outdated_sports, topic="sports", section=None,
            philippines_only=True, start=start, end=end,
        ))
        self.assertFalse(main._matches_research_filters(
            international_sports, topic="sports", section=None,
            philippines_only=True, start=start, end=end,
        ))

    def test_research_trend_sources_include_publication_metadata(self):
        article = {
            "id": "trend-1",
            "title": "Basketball league opens finals",
            "summary": "The teams begin a championship series.",
            "source": "MIRA Sports Desk",
            "category": "Sports",
            "published": "2026-03-20T08:00:00Z",
            "url": "https://www.rappler.com/sports/finals",
        }

        reply = main._append_research_source_references(
            "## Trend\nBasketball finals begin [S1].", [article]
        )

        self.assertIn("Category: Sports · Published: 2026-03-20", reply)
        self.assertIn("Basketball league opens finals — MIRA Sports Desk", reply)
        self.assertIn(article["url"], reply)
        article_header = main._research_article_header([article])
        self.assertIn("**Category:** Sports", article_header)
        self.assertRegex(article_header, r"\*\*Publication date:\*\* \d{4}-\d{2}-\d{2} \(draft\)")

    def test_trend_summary_omits_truncated_feed_fragments(self):
        summary = main._trend_summary({
            "summary": "First complete sentence. Second complete sentence! Broken quote “",
        })

        self.assertEqual(summary, "First complete sentence. Second complete sentence!")

    def test_trend_request_groups_and_ranks_only_matching_stored_records(self):
        now = datetime.now(timezone.utc)
        articles = [
            {
                "id": "finals-1",
                "title": "Basketball finals begin in Manila",
                "summary": "The series opens today.",
                "source": "Rappler",
                "section": "national",
                "category": "Sports",
                "topics": ["basketball"],
                "published": (now - timedelta(hours=1)).isoformat(),
                "url": "https://www.rappler.com/sports/finals-1",
            },
            {
                "id": "finals-2",
                "title": "Basketball finals begin in Manila after a close season",
                "summary": "Teams start the championship series.",
                "source": "Inquirer",
                "section": "national",
                "category": "Sports",
                "topics": ["basketball"],
                "published": now.isoformat(),
                "url": "https://www.inquirer.net/sports/finals-2",
            },
            {
                "id": "team-3",
                "title": "Basketball team wins a national championship",
                "summary": "The squad claims the season title.",
                "source": "GMA",
                "section": "national",
                "category": "Sports",
                "topics": ["basketball"],
                "published": now.isoformat(),
                "url": "https://www.gmanetwork.com/sports/team-3",
            },
        ]

        with (
            patch.object(main.news, "ensure_stored_cache_loaded") as ensure_cache,
            patch.object(main, "_retrieve", return_value=articles),
            patch.object(main.intelligence, "fast_search") as fast_search,
        ):
            context = main._research_context(
                [{"role": "user", "content": "Can you show me the top 5 freshest sports news today"}],
                "auto",
            )
            analysis_context = main._research_context(
                [{"role": "user", "content": "Why are the sports stories trending today?"}],
                "auto",
            )

        self.assertEqual(ensure_cache.call_count, 2)
        fast_search.assert_not_called()
        self.assertFalse(context["analysis"])
        self.assertTrue(analysis_context["analysis"])
        self.assertEqual(
            main._research_query("Can you show me the top 5 freshest sports news today"),
            "sports",
        )
        self.assertEqual(context["trend_ids"], ["finals-2", "team-3"])
        self.assertEqual(context["source_ids"], ["finals-2", "team-3", "finals-1"])
        self.assertIn("Related coverage", context["prefix"])
        self.assertIn("[S3]", context["prefix"])

    def test_chat_reports_insufficient_trend_records_without_calling_the_ai(self):
        with (
            patch.object(main.news, "ensure_stored_cache_loaded"),
            patch.object(main, "_retrieve", return_value=[]),
            patch.object(main.ai, "_need_client") as need_client,
            patch.object(main, "_save_turn", return_value=None),
        ):
            result = main.chat(main.ChatIn(messages=[
                main.Msg(role="user", content="What are the trending sports stories today?")
            ]), uid=None, stream=False)
            article_result = main.chat(main.ChatIn(messages=[
                main.Msg(role="user", content="Create an article about trending sports today.")
            ]), uid=None, stream=False)

        self.assertIn("do not contain enough matching", result["reply"])
        self.assertIn("do not contain enough matching", article_result["reply"])
        self.assertNotIn("MIRA AI DRAFT", article_result["reply"])
        need_client.assert_not_called()

    def test_list_only_trend_response_uses_grouped_records_without_extra_ai_text(self):
        async def collect(response):
            return [
                chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                async for chunk in response.body_iterator
            ]

        now = datetime.now(timezone.utc)
        articles = [
            {
                "id": "herro-report",
                "title": "NBA: Tyler Herro's 50 points not enough to lift Bucks over 76ers",
                "summary": "Tyler Herro scored 50 points in a 76ers win over Milwaukee.",
                "source": "Philippine Daily Inquirer",
                "section": "national",
                "category": "national",
                "topics": ["basketball"],
                "published": now.isoformat(),
                "url": "https://www.inquirer.net/sports/herro-report",
            },
            {
                "id": "embiid-report",
                "title": "NBA: Joel Embiid sparks 76ers to win over Tyler Herro, Bucks",
                "summary": "Joel Embiid led Philadelphia past Milwaukee.",
                "source": "Philippine Daily Inquirer",
                "section": "national",
                "category": "national",
                "topics": ["basketball"],
                "published": (now - timedelta(hours=1)).isoformat(),
                "url": "https://www.inquirer.net/sports/embiid-report",
            },
        ]
        body = main.ChatIn(messages=[
            main.Msg(
                role="user",
                content="Can you show me the top 5 freshest sports news today",
            )
        ])

        with (
            patch.object(main.news, "ensure_stored_cache_loaded"),
            patch.object(main, "_retrieve", return_value=articles),
            patch.object(main.ai, "_need_client") as need_client,
            patch.object(main.ai, "chat") as chat,
            patch.object(main, "_save_turn", return_value=None),
        ):
            result = main.chat(body, uid=None, stream=False)
            stream_response = main.chat(body, uid=None, stream=True)
            events = asyncio.run(collect(stream_response))
            done = next(
                json.loads(event.removeprefix("data: ").strip())
                for event in events
                if '"type": "done"' in event
            )

        self.assertEqual(len(re.findall(r"(?m)^\d+\.", result["reply"])), 1)
        self.assertIn("Related coverage", result["reply"])
        self.assertNotIn("live wire", result["reply"].casefold())
        self.assertNotIn("Based on the available records", result["reply"])
        self.assertIn("Related coverage", done["reply"])
        self.assertNotIn("live wire", done["reply"].casefold())
        need_client.assert_not_called()
        chat.assert_not_called()

    def test_research_context_marker_preserves_numbered_trend_followups(self):
        saved = main._with_research_context(
            "1. First story [S1]\n2. Second story [S2]",
            ["first-id", "second-id"],
            ["first-id", "second-id"],
        )
        messages = [
            {"role": "assistant", "content": saved},
            {"role": "user", "content": "Make an article about number 2."},
        ]

        context = main._previous_research_context(messages)

        self.assertEqual(context["sources"], ["first-id", "second-id"])
        self.assertEqual(context["trends"], ["first-id", "second-id"])
        self.assertEqual(main._numbered_reference(messages[-1]["content"]), 2)
        self.assertNotIn("MIRA_RESEARCH", main._messages_for_research_model(messages)[0]["content"])

    def test_image_retrieval_requires_matching_specific_topic_terms(self):
        articles = [
            {
                "id": "pax-silica",
                "title": "Pax Silica protesters gather",
                "summary": "Demonstrators challenge the Pax Silica issue.",
                "url": "https://www.rappler.com/news/pax-silica",
            },
            {
                "id": "unrelated",
                "title": "World of video games",
                "summary": "A guide to classic games and new releases.",
                "url": "https://www.bbc.com/news/games",
            },
            {
                "id": "generic-protest",
                "title": "Protesters gather downtown",
                "summary": "A local rally draws a crowd.",
                "url": "https://www.inquirer.net/news/protest",
            },
            {
                "id": "unrelated-headline",
                "title": "Judy Collins reflects on her music career",
                "summary": "The article briefly mentions Pax Silica in passing.",
                "url": "https://www.bbc.com/news/music",
            },
        ]
        with (
            patch.object(main.news, "list_articles", return_value=articles),
            patch.object(
                main.intelligence, "fast_search",
                return_value=(articles, None),
            ) as search,
        ):
            results = main._retrieve(
                "Please describe the protesters in Pax Silica",
                strict_image_relevance=True,
            )

        self.assertEqual([article["id"] for article in results], ["pax-silica"])
        self.assertEqual(search.call_args.args[2], len(articles))

    def test_image_retrieval_context_includes_recent_user_topic(self):
        context = main._upload_retrieval_context([
            {"role": "user", "content": "I am researching protests around Pax Silica."},
            {"role": "assistant", "content": "What would you like to know?"},
            {"role": "user", "content": "Please describe this image."},
        ])

        self.assertIn("Pax Silica", context)
        self.assertIn("describe this image", context)

    def test_explicit_image_topic_takes_precedence_over_older_chat_topics(self):
        context = main._upload_retrieval_context([
            {"role": "user", "content": "Tell me about Judy Collins."},
            {"role": "user", "content": "Analyze the Pax Silica protest image."},
        ])

        self.assertIn("Pax Silica", context)
        self.assertNotIn("Judy Collins", context)

    def test_generic_image_prompt_does_not_attach_arbitrary_sources(self):
        articles = [{
            "id": "story",
            "title": "Latest story",
            "summary": "A news report.",
            "url": "https://www.rappler.com/news/story",
        }]
        with (
            patch.object(main.news, "list_articles", return_value=articles),
            patch.object(
                main.intelligence, "fast_search",
                return_value=(articles, None),
            ),
        ):
            results = main._retrieve(
                "Please analyze this image and describe what is visible",
                strict_image_relevance=True,
            )

        self.assertEqual(results, [])

    def test_chat_retrieval_uses_cached_bm25_without_embedding_migration(self):
        articles = [
            {
                "id": "article-1",
                "title": "Local farming update",
                "summary": "Rice harvest",
                "url": "https://www.bbc.com/news/story",
            },
        ]
        with (
            patch.object(main.news, "list_articles", return_value=articles),
            patch.object(
                main.intelligence, "fast_search", return_value=(articles, None)
            ) as fast_search,
            patch.object(main.intelligence, "hybrid_search") as hybrid_search,
        ):
            result = main._retrieve("farming update")
        self.assertEqual(result, articles)
        hybrid_search.assert_not_called()
        fast_search.assert_called_once_with("farming update", articles, 5)

    def test_chat_retrieval_uses_context_for_short_followups(self):
        query = main._chat_retrieval_query([
            {"role": "user", "content": "What is the confidential funds investigation?"},
            {"role": "assistant", "content": "It concerns public spending."},
            {"role": "user", "content": "Why?"},
        ])

        self.assertIn("confidential", query)
        self.assertIn("fund", query)

    def test_chat_does_not_search_news_for_a_greeting(self):
        with (
            patch.object(main.news, "ensure_stored_cache_loaded"),
            patch.object(main, "_retrieve") as retrieve,
            patch.object(main.news, "search_discovery") as search,
        ):
            result = main._research_context(
                [{"role": "user", "content": "Thanks!"}], "auto"
            )

        self.assertEqual(result["sources"], [])
        retrieve.assert_not_called()
        search.assert_not_called()

    def test_chat_does_not_wait_for_archive_or_live_search_for_general_questions(self):
        with (
            patch.object(main.news, "ensure_stored_cache_loaded") as ensure_cache,
            patch.object(main, "_retrieve") as retrieve,
            patch.object(main.news, "search_discovery") as search,
        ):
            result = main._research_context(
                [{"role": "user", "content": "Why is the sky blue?"}], "auto"
            )

        self.assertEqual(result["sources"], [])
        ensure_cache.assert_not_called()
        retrieve.assert_not_called()
        search.assert_not_called()

    def test_chat_research_searches_live_and_filters_untrusted_or_irrelevant_results(self):
        live_articles = [
            {
                "id": "relevant",
                "title": "Confidential funds inquiry seeks new records",
                "summary": "Investigators requested documents about confidential funds.",
                "source": "Rappler",
                "url": "https://www.rappler.com/news/confidential-funds",
            },
            {
                "id": "irrelevant",
                "title": "Coastal towns prepare for heavy rain",
                "summary": "Local officials issued a weather advisory.",
                "source": "BBC",
                "url": "https://www.bbc.com/news/weather",
            },
            {
                "id": "untrusted",
                "title": "Confidential funds inquiry seeks new records",
                "summary": "Investigators requested documents about confidential funds.",
                "source": "Unverified",
                "url": "https://unverified.example/news/story",
            },
        ]
        messages = [
            {"role": "user", "content": "What is happening with the confidential funds inquiry?"},
            {"role": "assistant", "content": "It concerns public spending."},
            {"role": "user", "content": "Why is this still happening today?"},
        ]

        with (
            patch.object(main.news, "ensure_stored_cache_loaded"),
            patch.object(main, "_retrieve", return_value=[]),
            patch.object(
                main.news,
                "search_discovery",
                return_value={"articles": live_articles, "source_errors": []},
            ) as search,
            patch.object(main.news, "_decode_google_news_urls", return_value={}),
        ):
            result = main._research_context(messages, "auto")

        self.assertEqual([source["id"] for source in result["sources"]], ["relevant"])
        self.assertIn("confidential", search.call_args.args[0])
        self.assertTrue(result["sources"])
        self.assertFalse(result["live_search_failed"])

    def test_trusted_live_search_resolves_google_news_links_before_allowlisting(self):
        article = {
            "id": "google-result",
            "title": "Trusted report",
            "url": "https://news.google.com/rss/articles/encoded",
        }
        with patch.object(
            main.news,
            "_decode_google_news_urls",
            return_value={
                article["url"]: "https://www.rappler.com/news/trusted-report"
            },
        ):
            results = main._trusted_search_articles([article])

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["url"], "https://www.rappler.com/news/trusted-report"
        )

    def test_chat_retrieval_excludes_unapproved_publishers(self):
        articles = [
            {"id": "trusted", "url": "https://news.bbc.co.uk/story"},
            {"id": "untrusted", "url": "https://random-news.example/story"},
            {"id": "spoofed", "url": "https://bbc.com.random-news.example/story"},
            {"id": "insecure", "url": "http://bbc.com/story"},
        ]
        with (
            patch.object(main.news, "list_articles", return_value=articles),
            patch.object(main.intelligence, "fast_search", return_value=([], None)) as search,
        ):
            main._retrieve("news")
        self.assertEqual(search.call_args.args[1], [articles[0]])

    def test_chat_retrieval_drops_unapproved_thumbnail_hosts(self):
        articles = [
            {
                "id": "untrusted-image",
                "url": "https://bbc.com/news/story",
                "image": "https://images.example.test/photo.jpg",
            },
            {
                "id": "trusted-image",
                "url": "https://bbc.com/news/another-story",
                "image": "https://cdn.rappler.com/photo.jpg",
            },
        ]
        with (
            patch.object(main.news, "list_articles", return_value=articles),
            patch.object(
                main.intelligence,
                "fast_search",
                return_value=(articles, None),
            ),
        ):
            results = main._retrieve("news")
        self.assertNotIn("image", results[0])
        self.assertEqual(results[1]["image"], articles[1]["image"])

    def test_upload_retrieval_query_uses_filenames_and_text(self):
        query = main._upload_retrieval_query("Is this accurate?", [
            {
                "name": "Flood-Control-1024x536.webp",
                "mime_type": "image/webp",
                "data": b"image bytes",
            },
            {
                "name": "notes.txt",
                "mime_type": "text/plain",
                "data": b"Department budget claim",
            },
        ])
        self.assertIn("Flood Control 1024x536", query)
        self.assertIn("Department budget claim", query)

    def test_chat_with_files_passes_transient_text_content_to_gemini(self):
        class FakeModels:
            def __init__(self):
                self.calls = []

            def generate_content(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(text="Draft feedback")

        models = FakeModels()
        with patch.object(ai, "_client", SimpleNamespace(models=models)):
            reply = ai.chat_with_files(
                [{"role": "user", "content": "Review this draft."}],
                [{
                    "name": "draft.txt",
                    "mime_type": "text/plain",
                    "data": b"An article draft.",
                }],
            )
        self.assertEqual(reply, "Draft feedback")
        parts = models.calls[0]["contents"][0].parts
        self.assertEqual(parts[-1].text, "An article draft.")
        self.assertIn("draft.txt", parts[-2].text)

    def test_chat_with_files_passes_image_bytes_to_gemini(self):
        class FakeModels:
            def __init__(self):
                self.calls = []

            def generate_content(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(text="Image analysis")

        models = FakeModels()
        with patch.object(ai, "_client", SimpleNamespace(models=models)):
            reply = ai.chat_with_files(
                [{"role": "user", "content": "Analyze this image."}],
                [{
                    "name": "photo.png",
                    "mime_type": "image/png",
                    "data": b"image bytes",
                }],
            )

        self.assertEqual(reply, "Image analysis")
        image_part = models.calls[0]["contents"][0].parts[-1]
        self.assertEqual(image_part.inline_data.mime_type, "image/png")
        self.assertEqual(image_part.inline_data.data, b"image bytes")

    def test_chat_tries_all_gemini_fallbacks_after_model_rejection(self):
        rejected = ai.errors.APIError.__new__(ai.errors.APIError)
        Exception.__init__(rejected, "model unavailable")
        rejected.code = 400

        class FakeModels:
            calls = []

            def generate_content(self, **kwargs):
                self.calls.append(kwargs["model"])
                if len(self.calls) < 3:
                    raise rejected
                return SimpleNamespace(text="Recovered response", usage_metadata=None)

        models = FakeModels()
        config = ai.types.GenerateContentConfig(system_instruction="Be accurate.")
        with (
            patch.object(ai.providers, "sb", None),
            patch.object(
                ai.providers, "models_for",
                return_value=[SimpleNamespace(provider="huggingface")],
            ),
            patch.object(
                ai.providers, "provider_rank",
                side_effect=lambda provider: 1 if provider == "huggingface" else 0,
            ),
        ):
            result = ai._generate_content(
                SimpleNamespace(models=models),
                model=ai.GEMINI_MODEL,
                contents="Question",
                config=config,
            )

        self.assertEqual(result.text, "Recovered response")
        self.assertEqual(len(models.calls), 3)

    def test_chat_stream_tries_all_gemini_fallbacks_after_model_rejection(self):
        rejected = ai.errors.APIError.__new__(ai.errors.APIError)
        Exception.__init__(rejected, "model unavailable")
        rejected.code = 400

        class FakeModels:
            calls = []

            def generate_content_stream(self, **kwargs):
                self.calls.append(kwargs["model"])
                if len(self.calls) < 3:
                    raise rejected
                return iter([SimpleNamespace(text="Recovered response")])

        models = FakeModels()
        config = ai.types.GenerateContentConfig(system_instruction="Be accurate.")
        with (
            patch.object(ai.providers, "sb", None),
            patch.object(
                ai.providers, "models_for",
                return_value=[SimpleNamespace(provider="huggingface")],
            ),
            patch.object(
                ai.providers, "provider_rank",
                side_effect=lambda provider: 1 if provider == "huggingface" else 0,
            ),
        ):
            result = list(ai._generate_content_stream(
                SimpleNamespace(models=models),
                model=ai.GEMINI_MODEL,
                contents="Question",
                config=config,
                task="general_chat",
            ))

        self.assertEqual(result, ["Recovered response"])
        self.assertEqual(len(models.calls), 3)

    def test_chat_stream_yields_gemini_chunks_as_they_arrive(self):
        class FakeModels:
            def generate_content_stream(self, **kwargs):
                self.config = kwargs["config"]
                return iter([
                    SimpleNamespace(text="First"),
                    SimpleNamespace(text=" chunk"),
                ])

        models = FakeModels()
        with patch.object(ai, "_client", SimpleNamespace(models=models)):
            chunks = list(ai.chat_stream([{"role": "user", "content": "Hello"}]))

        self.assertEqual(chunks, ["First", " chunk"])
        self.assertEqual(models.config.max_output_tokens, ai._DEFAULT_CHAT_OUTPUT_TOKENS)

    def test_chat_stream_continues_if_gemini_hits_output_limit(self):
        class FakeModels:
            def __init__(self):
                self.calls = []

            def generate_content_stream(self, **kwargs):
                self.calls.append(kwargs)
                text, reason = (
                    ("An unfinished", "MAX_TOKENS")
                    if len(self.calls) == 1
                    else (" answer.", "STOP")
                )
                return iter([SimpleNamespace(
                    text=text,
                    candidates=[SimpleNamespace(finish_reason=reason)],
                )])

        models = FakeModels()
        with patch.object(ai, "_client", SimpleNamespace(models=models)):
            chunks = list(ai.chat_stream([{"role": "user", "content": "Check this claim."}]))

        self.assertEqual(chunks, ["An unfinished", " answer."])
        self.assertEqual(len(models.calls), 2)
        self.assertEqual(models.calls[1]["contents"][-1].role, "user")

    def test_chat_stream_falls_back_when_gemini_returns_malformed_chunk(self):
        class FakeModels:
            def __init__(self):
                self.calls = []

            def generate_content_stream(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    def broken_stream():
                        yield SimpleNamespace(
                            text="Partial answer",
                            candidates=[SimpleNamespace(finish_reason=None)],
                        )
                        raise json.JSONDecodeError("invalid chunk", "{bad", 1)

                    return broken_stream()
                return iter([SimpleNamespace(
                    text=" continued.",
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                )])

        models = FakeModels()
        with patch.object(ai, "_client", SimpleNamespace(models=models)):
            chunks = list(ai.chat_stream([
                {"role": "user", "content": "Give me a concise answer."},
            ]))

        self.assertEqual(chunks, ["Partial answer", " continued."])
        self.assertEqual(len(models.calls), 2)
        continuation = models.calls[1]["contents"]
        self.assertEqual(continuation[-2].role, "model")
        self.assertEqual(continuation[-2].parts[0].text, "Partial answer")
        self.assertEqual(continuation[-1].role, "user")

    def test_chat_stream_reports_repeated_output_limit_instead_of_success(self):
        class FakeModels:
            def generate_content_stream(self, **kwargs):
                return iter([SimpleNamespace(
                    text="Still incomplete",
                    candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
                )])

        with patch.object(ai, "_client", SimpleNamespace(models=FakeModels())):
            with self.assertRaisesRegex(RuntimeError, "may be incomplete"):
                list(ai.chat_stream([{"role": "user", "content": "Check this claim."}]))

    def test_stream_chat_response_emits_incremental_and_final_events(self):
        async def collect(response):
            return [
                chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                async for chunk in response.body_iterator
            ]

        with patch.object(main, "_save_turn", return_value="conversation-1"):
            response = main._stream_chat_response(
                iter(["First", " answer."]),
                [],
                None,
                None,
                "chat",
                None,
                "Hello",
            )
            events = asyncio.run(collect(response))

        self.assertEqual(response.media_type, "text/event-stream")
        self.assertIn('"type": "token", "text": "First"', events[0])
        self.assertIn('"type": "token", "text": " answer."', events[1])
        self.assertIn('"type": "done"', events[2])
        self.assertIn('"conversation_id": "conversation-1"', events[2])

    def test_streaming_chat_opens_before_live_source_research(self):
        body = main.ChatIn(messages=[
            main.Msg(role="user", content="Give me 4 sources related to Pax Silica")
        ])
        research = {
            "sources": [],
            "insufficient": None,
            "trend": False,
            "analysis": False,
            "prefix": "",
            "source_ids": [],
            "trend_ids": [],
        }

        with (
            patch.dict(main._SOURCE_LIST_CACHE, {}, clear=True),
            patch.object(main, "_research_context", return_value=research) as get_research,
            patch.object(ai, "_need_client"),
            patch.object(ai, "chat_stream", return_value=iter(["Here are sources."])),
            patch.object(main, "_save_turn", return_value="conversation-1"),
        ):
            response = main.chat(body, uid=None, stream=True)

            async def consume():
                iterator = response.body_iterator.__aiter__()
                first = await iterator.__anext__()
                first = first.decode("utf-8") if isinstance(first, bytes) else first
                self.assertIn('"type": "status"', first)
                self.assertIn("MIRA is analysing", first)
                get_research.assert_not_called()
                return [
                    first,
                    *[
                        chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                        async for chunk in iterator
                    ],
                ]

            events = asyncio.run(consume())

        get_research.assert_called_once()
        self.assertIn('"type": "done"', events[-1])

    def test_source_list_request_returns_retrieved_links_without_calling_ai(self):
        body = main.ChatIn(messages=[
            main.Msg(
                role="user",
                content="Give me at least 4 links or sources related to Pax Silica",
            )
        ])
        sources = [
            {
                "id": f"pax-{index}",
                "title": f"Pax Silica report {index}",
                "source": f"Publisher {index}",
                "url": f"https://publisher{index}.com/pax-silica",
            }
            for index in range(1, 3)
        ]
        research = {
            "sources": sources,
            "insufficient": None,
            "trend": False,
            "analysis": False,
            "prefix": "",
            "source_ids": ["pax-1", "pax-2"],
            "trend_ids": [],
        }

        with (
            patch.object(main, "_research_context", return_value=research),
            patch.object(ai, "_need_client") as need_client,
            patch.object(ai, "chat_stream") as chat_stream,
            patch.object(main, "_save_turn", return_value="conversation-1"),
        ):
            response = main.chat(body, uid=None, stream=True)
            events = asyncio.run(self._collect_stream_events(response))

        done = json.loads(events[-1].removeprefix("data: ").strip())
        self.assertIn(
            "I found 2 relevant trusted sources about Pax Silica (4 requested)",
            done["reply"],
        )
        self.assertIn("https://publisher1.com/pax-silica", done["reply"])
        self.assertIn("https://publisher2.com/pax-silica", done["reply"])
        self.assertNotIn("]([https://", done["reply"])
        need_client.assert_not_called()
        chat_stream.assert_not_called()
        self.assertTrue(main._is_source_list_only_request(
            "Give me at least 4 links related to Pax Silica"
        ))
        self.assertFalse(main._is_source_list_only_request(
            "Give me 4 links and explain what Pax Silica is"
        ))

    def test_complete_source_lists_are_cached_for_repeat_requests(self):
        prompt = "List 4 sources about orbital basalt cache speed check"
        sources = [
            {"id": f"cached-{index}", "url": f"https://source{index}.example/story"}
            for index in range(4)
        ]

        main._cache_source_list(prompt, sources)

        cached = main._cached_source_list_context(
            "Give me 4 links related to orbital basalt cache speed check"
        )
        self.assertIsNotNone(cached)
        self.assertEqual(cached["source_ids"], [f"cached-{index}" for index in range(4)])
        self.assertIsNone(main._cached_source_list_context(
            "Give me 5 links related to orbital basalt cache speed check"
        ))

    def test_repeat_source_request_uses_cached_results_without_live_research(self):
        prompt = "List 4 sources about lunar basalt speed validation"
        alternate_prompt = "Give me 4 links about lunar basalt speed validation"
        sources = [
            {
                "id": f"lunar-{index}",
                "title": f"Lunar basalt report {index}",
                "source": f"Publisher {index}",
                "url": f"https://publisher{index}.example/lunar-basalt",
            }
            for index in range(1, 5)
        ]
        research = {
            "sources": sources,
            "insufficient": None,
            "trend": False,
            "analysis": False,
            "prefix": "",
            "source_ids": [source["id"] for source in sources],
            "trend_ids": [],
        }

        with (
            patch.object(main, "_research_context", return_value=research) as search,
            patch.object(main, "_save_turn", return_value="conversation-1"),
        ):
            first = main.chat(main.ChatIn(messages=[
                main.Msg(role="user", content=prompt)
            ]), uid=None, stream=True)
            asyncio.run(self._collect_stream_events(first))

        with (
            patch.object(main, "_research_context") as search,
            patch.object(main, "_save_turn", return_value="conversation-2"),
        ):
            second = main.chat(main.ChatIn(messages=[
                main.Msg(role="user", content=alternate_prompt)
            ]), uid=None, stream=True)
            events = asyncio.run(self._collect_stream_events(second))

        search.assert_not_called()
        done = json.loads(events[-1].removeprefix("data: ").strip())
        self.assertIn("https://publisher4.example/lunar-basalt", done["reply"])

    @staticmethod
    async def _collect_stream_events(response):
        return [
            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            async for chunk in response.body_iterator
        ]

    def test_chat_upload_uses_multimodal_model_and_does_not_return_upload(self):
        uploaded = UploadFile(
            file=BytesIO(b"image bytes"),
            filename="photo.png",
            headers=Headers({"content-type": "image/png"}),
        )
        with (
            patch.object(main, "_retrieve", return_value=[]) as retrieve,
            patch.object(ai, "_client", SimpleNamespace()),
        ):
            with patch.object(ai, "chat_with_files", return_value="Review with limits.") as analyze:
                response = asyncio.run(main.chat_upload(
                    messages=json.dumps([{"role": "user", "content": "Review this image."}]),
                    files=[uploaded],
                    conversation_id=None,
                    project_id=None,
                    mode="media_review",
                    uid=None,
                ))

        payload = response
        self.assertEqual(payload["reply"].splitlines()[0], "Review with limits.")
        self.assertFalse(payload["uploads_retained"])
        self.assertNotIn("photo.png", json.dumps(payload))
        analyze.assert_called_once()
        self.assertEqual(analyze.call_args.args[1][0]["data"], b"image bytes")
        self.assertIn("photo", retrieve.call_args.args[0])

    def test_media_review_mode_never_claims_to_prove_authenticity(self):
        system = main._chat_system("media_review", [])
        self.assertIn("Supported, Misleading, False, or Unverified", system)
        self.assertIn("visual inspection alone cannot prove", system)
        self.assertIn("provenance", system)
        self.assertIn("at most 120 words", system)

    def test_auto_chat_mode_infers_user_intent_for_writing_and_verification(self):
        system = main._chat_system("auto", [])
        self.assertIn("Infer the user's goal", system)
        self.assertIn("constructive writing and reporting guidance", system)
        self.assertIn("a description request is not a request for fact-checking", system)
        self.assertIn("Give a verdict only when the user asks to verify", system)
        self.assertIn("Do not claim the image itself is authentic or fabricated", system)
        self.assertIn("at most 120 words", system)

    def test_research_system_discloses_failed_live_search(self):
        system = main._research_chat_system(
            "auto", [], {"live_search_failed": True}
        )

        self.assertIn("The live news search failed", system)
        self.assertIn("Do not describe stored records as current", system)
        self.assertIn(
            "Answer general-knowledge and journalism-method questions directly",
            system,
        )

    def test_explicit_article_request_uses_article_generation_task_and_prompt(self):
        body = main.ChatIn(
            messages=[main.Msg(
                role="user",
                content="Write a newspaper article about the supplied sources.",
            )],
        )
        with (
            patch.object(main, "_validate_chat_targets"),
            patch.object(main, "_retrieve", return_value=[]),
            patch.object(
                main.news,
                "search_discovery",
                return_value={"articles": [], "source_errors": []},
            ),
            patch.object(ai, "_need_client"),
            patch.object(ai, "chat", return_value="# Draft headline") as chat,
            patch.object(ai, "append_source_references", side_effect=lambda reply, *_: reply),
        ):
            result = main.chat(body, uid=None)

        self.assertEqual(result["reply"], "# Draft headline")
        self.assertEqual(chat.call_args.args[2], "article_generation")
        self.assertIn("MIRA AI DRAFT", chat.call_args.args[1])
        self.assertEqual(
            main._requested_chat_mode("auto", "How do I write a news article?"),
            "auto",
        )

    def test_article_generation_with_uploaded_images_remains_a_vision_task(self):
        self.assertEqual(
            main._chat_task("article_generation", has_images=True),
            "article_generation",
        )
        self.assertEqual(
            main._chat_task("auto", has_images=True),
            "image_analysis",
        )

    def test_article_analysis_maps_only_model_cited_source_ids(self):
        class FakeModels:
            def generate_content(self, **kwargs):
                return SimpleNamespace(text=json.dumps({
                    "main_issue": "Reported issue",
                    "cited_sources": ["S1", "S9"],
                }))

        article = {"title": "Current story", "source": "Daily News",
                   "url": "https://example.test/current"}
        sources = [{
            "title": "Related story", "source": "Example",
            "url": "https://example.test/related",
        }]
        with patch.object(ai, "_client", SimpleNamespace(models=FakeModels())):
            result = ai.analyze(article, "Article text.", sources)
        self.assertEqual(result["cited_sources"], [{
            "id": "S1", "title": "Related story", "source": "Example",
            "url": "https://example.test/related",
        }])

    def test_chat_and_story_analysis_use_separate_gemini_clients(self):
        class FakeModels:
            def __init__(self, response_text):
                self.response_text = response_text
                self.calls = []

            def generate_content(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(text=self.response_text)

        chat_models = FakeModels("chat reply")
        analysis_models = FakeModels(json.dumps({"main_issue": "Analysis"}))
        chat_client = SimpleNamespace(models=chat_models)
        analysis_client = SimpleNamespace(models=analysis_models)
        article = {"title": "Current story", "source": "Daily News",
                   "url": "https://example.test/current"}

        with (
            patch.object(ai, "_client", chat_client),
            patch.object(ai, "_analysis_client", analysis_client),
        ):
            self.assertEqual(ai.chat([{"role": "user", "content": "Hello"}]), "chat reply")
            self.assertEqual(ai.analyze(article, "Article text.")["main_issue"], "Analysis")

        self.assertEqual(len(chat_models.calls), 1)
        self.assertEqual(len(analysis_models.calls), 1)

    def test_chat_retries_transient_gemini_overload_with_fallback_model(self):
        overloaded = ai.errors.APIError.__new__(ai.errors.APIError)
        Exception.__init__(overloaded, "temporarily unavailable")
        overloaded.code = 503
        overloaded.status = "UNAVAILABLE"
        overloaded.details = {"message": "temporarily unavailable"}

        class FakeModels:
            def __init__(self):
                self.models = []

            def generate_content(self, **kwargs):
                self.models.append(kwargs["model"])
                if len(self.models) == 1:
                    raise overloaded
                return SimpleNamespace(text="Hello from fallback.")

        models = FakeModels()
        client = SimpleNamespace(models=models)
        with (
            patch.object(ai, "_client", client),
            patch.object(ai.providers, "models_for", return_value=[]),
        ):
            reply = ai.chat([{"role": "user", "content": "Hello"}])
        self.assertEqual(reply, "Hello from fallback.")
        self.assertEqual(models.models, [
            ai.GEMINI_MODEL,
            "gemini-3.5-flash-lite",
        ])

    def test_chat_does_not_retry_nontransient_gemini_errors(self):
        invalid_model = ai.errors.APIError.__new__(ai.errors.APIError)
        Exception.__init__(invalid_model, "model not found")
        invalid_model.code = 404
        invalid_model.status = "NOT_FOUND"
        invalid_model.details = {"message": "model not found"}

        class FakeModels:
            def __init__(self):
                self.calls = 0

            def generate_content(self, **kwargs):
                self.calls += 1
                raise invalid_model

        models = FakeModels()
        with patch.object(ai, "_client", SimpleNamespace(models=models)):
            with self.assertRaises(ai.errors.APIError):
                ai.chat([{"role": "user", "content": "Hello"}])
        self.assertEqual(models.calls, 1)

    def test_chat_stops_after_one_gemini_fallback_on_repeated_overload(self):
        overloaded = ai.errors.APIError.__new__(ai.errors.APIError)
        Exception.__init__(overloaded, "temporarily unavailable")
        overloaded.code = 503
        overloaded.status = "UNAVAILABLE"
        overloaded.details = {"message": "temporarily unavailable"}

        class FakeModels:
            def __init__(self):
                self.models = []

            def generate_content(self, **kwargs):
                self.models.append(kwargs["model"])
                if len(self.models) < 3:
                    raise overloaded
                return SimpleNamespace(text="Hello from second fallback.")

        models = FakeModels()
        with (
            patch.object(ai, "_client", SimpleNamespace(models=models)),
            patch.object(ai.providers, "models_for", return_value=[]),
        ):
            with self.assertRaises(ai.errors.APIError):
                ai.chat([{"role": "user", "content": "Hello"}])
        self.assertEqual(models.models, [
            ai.GEMINI_MODEL,
            "gemini-3.5-flash-lite",
        ])

    def test_story_analysis_falls_back_to_chat_key_when_dedicated_key_is_absent(self):
        fallback_client = SimpleNamespace(models=SimpleNamespace())
        with (
            patch.object(ai, "_client", fallback_client),
            patch.object(ai, "_analysis_client", None),
        ):
            self.assertIs(ai._need_analysis_client(), fallback_client)


if __name__ == "__main__":
    unittest.main()
