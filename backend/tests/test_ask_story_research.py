import asyncio
import json
import time
import unittest
from unittest.mock import call, patch

from app import ask_story, ask_story_research, main


class AskStoryResearchTests(unittest.TestCase):
    def test_only_https_allowlisted_publishers_are_accepted(self):
        self.assertEqual(
            ask_story_research._trusted_domain("https://www.reuters.com/world/story"),
            "reuters.com",
        )
        self.assertEqual(
            ask_story_research._trusted_domain("https://agency.gov.ph/release"),
            "agency.gov.ph",
        )
        self.assertIsNone(
            ask_story_research._trusted_domain("http://reuters.com/world/story")
        )
        self.assertIsNone(
            ask_story_research._trusted_domain("https://reuters.com.attacker.example/story")
        )

    def test_research_discloses_when_fewer_than_requested_publishers_are_found(self):
        related = [
            {
                "title": f"Mindanao Avenue lane expansion report {index}",
                "source": f"Publisher {index}",
                "url": f"https://{domain}/story",
                "summary": f"DPWH Mindanao Avenue lane expansion evidence excerpt {index} with enough detail to serve as a retrieved source snippet.",
            }
            for index, domain in enumerate(
                ("reuters.com", "apnews.com", "bbc.com", "dw.com"),
                start=1,
            )
        ]
        with patch.object(ask_story_research, "_google_news_candidates", return_value=[]), patch.object(
            ask_story_research, "_fetch_article_text", return_value=""
        ):
            sources, disclosure = ask_story_research.research_sources(
                {"title": "Mindanao Avenue lane expansion"},
                "Write a detailed article",
                related,
                limit=5,
            )

        self.assertEqual(len(sources), 4)
        self.assertIn("only 4 distinct", disclosure)
        self.assertIn("do not claim that 5 sources", disclosure)
        self.assertEqual([source["id"] for source in sources], ["S1", "S2", "S3", "S4"])

    def test_research_excludes_selected_publisher_and_unrelated_stories(self):
        article = {
            "title": "DPWH opens a westbound lane on Mindanao Avenue",
            "source": "BBC News",
            "url": "https://www.bbc.com/news/selected-story",
            "summary": "The project opens a new road lane to ease traffic in Caloocan City, Philippines.",
        }
        related = [
            {
                "title": "Mindanao Avenue lane expansion update",
                "source": "BBC News",
                "url": "https://www.bbc.com/news/duplicate-publisher",
                "summary": "DPWH opened an additional westbound lane in Caloocan City.",
            },
            {
                "title": "The Papers: Kate's road to recovery",
                "source": "Reuters",
                "url": "https://www.reuters.com/world/kate-road-recovery",
                "summary": "A UK royal recovery story mentions a road.",
            },
            {
                "title": "Trans-Central Highway: Crackdown on reckless motoring",
                "source": "Cebu Daily News",
                "url": "https://cebudailynews.inquirer.net/highway-crackdown",
                "summary": "Cebu traffic enforcement targets reckless motoring on local highways.",
            },
            {
                "title": "DPWH opens a Mindanao Avenue extension lane",
                "source": "Rappler",
                "url": "https://www.rappler.com/news/mindanao-avenue-lane",
                "summary": "The new lane opened in Caloocan after a DPWH inspection led by local transportation officials.",
            },
        ]
        with patch.object(
            ask_story_research, "_google_news_candidates", return_value=[]
        ), patch.object(
            ask_story_research, "_fetch_article_text", return_value=""
        ):
            sources, disclosure = ask_story_research.research_sources(
                article,
                "Give at least 3 sources related to this news",
                related,
                limit=3,
            )

        self.assertEqual(
            [source["domain"] for source in sources],
            ["inquirer.net", "rappler.com"],
        )
        self.assertIn("only 2 distinct", disclosure)
        self.assertIn("selected story and unrelated stories are excluded", disclosure)

    def test_explicit_source_topic_excludes_generic_campaign_matches(self):
        article = {
            "title": "DILG Caraga underscores LGU role in anti-drug campaign",
            "source": "Philippine Information Agency",
            "url": "https://pia.gov.ph/news/anti-drug-campaign",
            "summary": "The agency supports local governments in anti-drug efforts.",
        }
        request = "Give me 3 sources reports of anti drug campaign"
        candidates = [
            {
                "title": "Shabu seized in Caraga drug busts",
                "summary": "Police action supports the anti-drug campaign.",
                "domain": "rappler.com",
                "url": "https://www.rappler.com/philippines/caraga-drug-bust",
            },
            {
                "title": "Alice Huang had contact with China spy agency",
                "summary": "The report mentions a campaign during an Nvidia boss affair.",
                "domain": "nytimes.com",
                "url": "https://www.nytimes.com/world/alice-huang",
            },
            {
                "title": "DILG is latest government agency to report data leak",
                "summary": "The department reported a cybersecurity incident.",
                "domain": "inquirer.net",
                "url": "https://www.inquirer.net/news/dilg-data-leak",
            },
            {
                "title": "Knesset readies for new speaker",
                "summary": "Israeli opposition campaign prepares for a vote.",
                "domain": "apnews.com",
                "url": "https://apnews.com/article/knesset-speaker",
            },
        ]

        relevance = [
            ask_story_research._is_relevant_to_story(
                article,
                request,
                candidate,
                require_requested_topics=True,
            )
            for candidate in candidates
        ]
        contextual_relevance = [
            ask_story_research._is_relevant_to_story(
                article,
                "give 3 sources report related to this report",
                candidate,
                require_requested_topics=True,
            )
            for candidate in candidates
        ]

        self.assertEqual(relevance, [True, False, False, False])
        self.assertEqual(contextual_relevance, [True, False, False, False])

    def test_source_count_defaults_to_four_and_respects_explicit_request(self):
        self.assertEqual(
            ask_story_research.requested_source_count("Explain this story"),
            4,
        )
        self.assertEqual(
            ask_story_research.requested_source_count(
                "Explain this story using only three sources"
            ),
            3,
        )
        self.assertEqual(
            ask_story_research.requested_source_count("Give me up to 2 sources"),
            2,
        )
        self.assertEqual(
            ask_story_research.requested_source_count(
                "Give me at least 6 links related to Pax Silica"
            ),
            6,
        )
        self.assertEqual(
            ask_story_research.requested_source_count(
                "Provide at least 5 sources reports of Pax Silica issue"
            ),
            5,
        )
        self.assertEqual(
            ask_story_research.requested_source_count("List 3 key points"),
            4,
        )

    def test_chat_source_count_limits_retrieval_to_the_user_request(self):
        articles = [
            {"id": f"article-{index}", "title": f"Climate report {index}"}
            for index in range(1, 6)
        ]
        for prompt, expected_count in (
            ("Explain climate change", 4),
            ("Explain climate change using only 3 sources", 3),
        ):
            with (
                self.subTest(prompt=prompt),
                patch.object(main.news, "ensure_stored_cache_loaded"),
                patch.object(main, "_retrieve", return_value=articles),
                patch.object(
                    main.news,
                    "search_discovery",
                    return_value={"articles": [], "source_errors": []},
                ),
                patch.object(
                    main, "_rank_chat_sources",
                    side_effect=lambda _query, candidates, limit: candidates[:limit],
                ) as rank_sources,
            ):
                result = main._research_context(
                    [{"role": "user", "content": prompt}],
                    "chat",
                )

            self.assertEqual(len(result["sources"]), expected_count)
            self.assertEqual(rank_sources.call_args.kwargs["limit"], expected_count)

    def test_chat_source_request_uses_enough_captured_sources_without_external_search(self):
        articles = [
            {
                "id": f"pax-{index}",
                "title": f"Pax Silica coverage {index}",
                "summary": f"Reporting about Pax Silica in the Philippines, article {index}.",
                "source": f"Publisher {index}",
                "url": f"https://{('apnews.com', 'bbc.com')[index - 1]}/pax-silica",
            }
            for index in (1, 2)
        ]
        with (
            patch.dict(
                main.news._cache,
                {"items": articles, "stored_loaded": False},
            ),
            patch.object(main.news, "ensure_stored_cache_loaded") as ensure_stored,
            patch.object(main, "_retrieve", return_value=articles),
            patch.object(main, "_rank_chat_sources", return_value=articles),
            patch.object(main.news, "search_discovery") as search,
        ):
            started = time.perf_counter()
            result = main._research_context(
                [{"role": "user", "content": "Find 2 sources about Pax Silica"}],
                "chat",
            )
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 5.0)
        ensure_stored.assert_not_called()
        search.assert_not_called()
        self.assertEqual(
            [source["retrieval_origin"] for source in result["sources"]],
            ["captured", "captured"],
        )
        reply = main._append_research_source_references(
            "Here are the sources.", result["sources"], include_all_sources=True
        )
        self.assertIn("Captured by MIRA", reply)
        self.assertIn(articles[0]["url"], reply)

    def test_warm_cache_pax_source_request_skips_archive_reload(self):
        domains = (
            "apnews.com",
            "bbc.com",
            "reuters.com",
            "pna.gov.ph",
            "rappler.com",
        )
        articles = [
            {
                "id": f"pax-{index}",
                "title": f"Pax Silica report {index}",
                "summary": "Pax Silica coverage and responses in the Philippines.",
                "source": f"Publisher {index}",
                "url": f"https://{domain}/pax-silica",
            }
            for index, domain in enumerate(domains, start=1)
        ]
        with (
            patch.dict(
                main.news._cache,
                {"items": articles, "stored_loaded": False},
            ),
            patch.object(main.news, "ensure_stored_cache_loaded") as ensure_stored,
            patch.object(main, "_retrieve") as retrieve,
            patch.object(main, "_rank_chat_sources") as bm25_search,
            patch.object(main.news, "search_discovery") as search,
        ):
            started = time.perf_counter()
            result = main._research_context(
                [{
                    "role": "user",
                    "content": "Provide at least 5 sources reports of Pax Silica issue",
                }],
                "chat",
            )
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 5.0)
        ensure_stored.assert_not_called()
        retrieve.assert_not_called()
        bm25_search.assert_not_called()
        search.assert_not_called()
        self.assertEqual(len(result["sources"]), 5)
        self.assertEqual(
            ask_story_research.requested_source_count(
                "Provide at least 5 sources reports of Pax Silica issue"
            ),
            5,
        )

    def test_incomplete_source_lists_are_not_cached_as_complete(self):
        prompt = "List 4 sources about cache-shortfall volcano"
        sources = [{
            "id": "captured-volcano",
            "title": "Volcano report",
            "source": "Publisher",
            "url": "https://publisher.example/volcano",
        }]

        main._cache_source_list(prompt, sources)

        cached = main._cached_source_list_context(
            "Give me 4 links about cache-shortfall volcano"
        )
        self.assertIsNone(cached)

    def test_incomplete_ask_story_source_lists_are_not_cached_as_complete(self):
        article = {"id": "volcano-story", "title": "Volcano briefing"}
        prompt = "Find 3 sources about cache-shortfall volcano"
        sources = [{
            "id": "S1",
            "title": "Volcano report",
            "url": "https://publisher.example/volcano",
        }]

        main._cache_ask_story_sources(article, prompt, 3, sources)

        self.assertIsNone(
            main._cached_ask_story_sources(
                article, "Give me 3 links about cache-shortfall volcano", 3
            )
        )

    def test_ask_story_source_cache_rejects_stale_unrelated_results(self):
        article = {
            "id": "dilg-caraga-story",
            "title": "DILG Caraga underscores LGU role in anti-drug campaign",
            "source": "Philippine Information Agency",
            "url": "https://pia.gov.ph/news/anti-drug-campaign",
        }
        prompt = "give 3 sources report related to this report"
        cached_sources = [
            {
                "title": "8 nabbed, shabu seized in Caraga drug busts",
                "summary": "Police support the anti-drug campaign.",
                "source": "Philippine Daily Inquirer",
                "url": "https://newsinfo.inquirer.net/caraga-drug-bust",
            },
            {
                "title": "Alice Huang had contact with China spy agency during affair with Nvidia boss, New York Times reports",
                "summary": "A report on China and Nvidia.",
                "source": "France 24",
                "url": "https://www.france24.com/en/americas/alice-huang",
            },
            {
                "title": "As Knesset readies for new speaker, Israeli opposition holds powerful role",
                "summary": "The latest Israeli political developments.",
                "source": "Al Jazeera",
                "url": "https://www.aljazeera.com/news/knesset-speaker",
            },
        ]

        with patch.dict(main._ASK_STORY_SOURCE_CACHE, {}, clear=True):
            main._cache_ask_story_sources(article, prompt, 3, cached_sources)

            cached = main._cached_ask_story_sources(article, prompt, 3)

        self.assertIsNone(cached)

    def test_quick_article_lookup_skips_synchronous_image_enrichment(self):
        article = {
            "id": "quick-story",
            "url": "https://news.example.test/story",
            "image": None,
        }
        with patch.dict(main.news._by_id, {"quick-story": article}), patch.object(
            main.news, "_page_image"
        ) as page_image:
            result = main.news.get_article("quick-story", enrich_image=False)

        self.assertIs(result, article)
        page_image.assert_not_called()

    def test_source_search_loads_archive_when_live_cache_is_warm(self):
        with (
            patch.dict(
                main.news._cache,
                {"items": [{"id": "live-article"}], "stored_loaded": False},
            ),
            patch.object(main.news, "_load_stored_once") as load_stored,
        ):
            main.news.ensure_stored_cache_loaded()

        load_stored.assert_called_once_with(force=True)

    def test_chat_source_followup_uses_assistant_topic_and_lists_only_relevant_sources(self):
        messages = [
            {
                "role": "user",
                "content": "Identify the 5Ws and 1H of the news story in the image.",
            },
            {
                "role": "assistant",
                "content": (
                    "The image shows a protest against Pax Silica. The banners say "
                    "'No to Pax Silica'; indigenous people, farmers, and youth activists "
                    "are protesting the Pax Silica initiative in the Philippines."
                ),
            },
            {
                "role": "user",
                "content": "Give at least 4 sources related to the topic.",
            },
        ]
        live_articles = [
            {
                "id": "pax-rappler",
                "title": "Pax Silica protest draws Filipino student groups",
                "summary": "Activists protest the Pax Silica initiative in the Philippines.",
                "source": "Rappler",
                "url": "https://www.rappler.com/news/pax-silica-protest",
            },
            {
                "id": "pax-inquirer",
                "title": "Filipino groups raise concerns over Pax Silica",
                "summary": "The debate over Pax Silica draws protest from farmers and students.",
                "source": "Philippine Daily Inquirer",
                "url": "https://www.inquirer.net/news/pax-silica",
            },
            {
                "id": "unrelated",
                "title": "The Papers: Kate's road to recovery",
                "summary": "UK royal news and political updates.",
                "source": "BBC News",
                "url": "https://www.bbc.com/news/kate-recovery",
            },
        ]
        with (
            patch.dict(main.news._cache, {"items": []}),
            patch.object(
                main.ask_story_research,
                "external_sources",
                return_value=live_articles[:2],
            ) as external_search,
            patch.object(main.news, "search_discovery") as search,
        ):
            result = main._research_context(messages, "auto")

        self.assertIn("pax", external_search.call_args.args[0].casefold())
        self.assertIn("silica", external_search.call_args.args[0].casefold())
        search.assert_not_called()
        self.assertEqual(
            [source["id"] for source in result["sources"]],
            ["pax-rappler", "pax-inquirer"],
        )
        self.assertTrue(result["include_all_sources"])

        reply = main._append_research_source_references(
            "Here are relevant sources.",
            result["sources"],
            include_all_sources=result["include_all_sources"],
        )
        self.assertIn("https://www.rappler.com/news/pax-silica-protest", reply)
        self.assertIn("https://www.inquirer.net/news/pax-silica", reply)
        self.assertNotIn("kate-recovery", reply)

    def test_chat_sources_include_only_one_article_per_publisher(self):
        articles = [
            {
                "id": "inquirer-one",
                "title": "Pax Silica debate in the Philippines",
                "summary": "Philippine groups discuss Pax Silica.",
                "url": "https://www.inquirer.net/news/pax-silica",
            },
            {
                "id": "inquirer-two",
                "title": "Pax Silica draws attention in the Philippines",
                "summary": "More Philippine coverage of Pax Silica.",
                "url": "https://business.inquirer.net/news/pax-silica",
            },
            {
                "id": "rappler",
                "title": "Pax Silica questions in the Philippines",
                "summary": "Philippine groups question Pax Silica.",
                "url": "https://www.rappler.com/technology/pax-silica",
            },
            {
                "id": "bbc-uk",
                "title": "Pax Silica and the Philippines",
                "summary": "Coverage of Pax Silica in the Philippines.",
                "url": "https://www.bbc.co.uk/news/pax-silica",
            },
            {
                "id": "bbc-com",
                "title": "Pax Silica and Philippine policy",
                "summary": "Coverage of Pax Silica in the Philippines.",
                "url": "https://www.bbc.com/news/pax-silica",
            },
            {
                "id": "ap",
                "title": "Pax Silica impacts the Philippines",
                "summary": "Philippine groups respond to Pax Silica.",
                "url": "https://apnews.com/article/pax-silica",
            },
        ]
        with patch.object(
            main.intelligence,
            "fast_search",
            return_value=(articles, None),
        ):
            sources = main._rank_chat_sources(
                "Pax Silica Philippines", articles, limit=4
            )

        self.assertEqual(
            [source["id"] for source in sources],
            ["inquirer-one", "rappler", "bbc-uk", "ap"],
        )

    def test_chat_source_fallback_searches_once_after_captured_sources(self):
        messages = [{
            "role": "user",
            "content": "Give me at least 4 sources related to Pax Silica Philippines",
        }]
        captured = [
            {
                "id": "pax-inquirer",
                "title": "Pax Silica debate in the Philippines",
                "summary": "Philippine groups discuss Pax Silica.",
                "url": "https://www.inquirer.net/news/pax-silica",
            },
            {
                "id": "pax-rappler",
                "title": "Pax Silica questions in the Philippines",
                "summary": "Philippine groups question Pax Silica.",
                "url": "https://www.rappler.com/technology/pax-silica",
            },
        ]
        external = [
            {
                "id": "pax-ap",
                "title": "Pax Silica and the Philippines",
                "summary": "The Philippines responds to Pax Silica.",
                "url": "https://apnews.com/article/pax-silica",
            },
            {
                "id": "pax-reuters",
                "title": "Pax Silica and Philippine policy",
                "summary": "Philippine policy on Pax Silica.",
                "url": "https://www.reuters.com/world/pax-silica",
            },
        ]
        with (
            patch.dict(main.news._cache, {"items": captured}),
            patch.object(
                main.ask_story_research,
                "external_sources",
                return_value=external,
            ) as external_search,
            patch.object(main.news, "search_discovery") as search,
        ):
            result = main._research_context(messages, "auto")

        self.assertEqual(
            [source["id"] for source in result["sources"]],
            ["pax-inquirer", "pax-rappler", "pax-ap", "pax-reuters"],
        )
        external_search.assert_called_once()
        search.assert_not_called()

    def test_ask_story_uses_default_and_requested_source_counts(self):
        article = {"id": "story-id", "title": "Selected story"}
        cases = (
            ("What does this mean?", 4, False),
            ("Find 3 sources about this story", 3, True),
        )
        for prompt, expected_count, deep_research in cases:
            with (
                self.subTest(prompt=prompt),
                patch.object(
                    main.news, "get_article", return_value=article
                ) as get_article,
                patch.object(
                    main.news, "article_text", return_value="Article text"
                ) as article_text,
                patch.object(main.news, "ensure_stored_cache_loaded"),
                patch.object(main, "_retrieve", return_value=[]) as retrieve,
                patch.object(
                    main.ask_story_research,
                    "research_sources",
                    return_value=([], "Research retrieval found no sources."),
                ) as research_sources,
                patch.object(main, "_ai_language_instruction", return_value=""),
                patch.object(
                    main.ask_story, "generate", return_value=("Answer", "model")
                ) as generate,
                patch.object(main.ask_story, "append_sources", return_value="Answer"),
                patch.object(main, "_save_story_turn", return_value=None),
            ):
                main.ask(
                    main.AskIn(
                        article_id="story-id",
                        messages=[main.Msg(role="user", content=prompt)],
                    ),
                    uid=None,
                )

            if prompt == "Find 3 sources about this story":
                retrieve.assert_not_called()
            else:
                self.assertEqual(retrieve.call_args.kwargs["limit"], expected_count)
            get_article.assert_called_once_with(
                "story-id", enrich_image=False
            )
            self.assertEqual(research_sources.called, deep_research)
            source_list_only = prompt == "Find 3 sources about this story"
            self.assertEqual(article_text.called, deep_research and not source_list_only)
            self.assertEqual(generate.called, not source_list_only)
            if deep_research:
                self.assertEqual(
                    research_sources.call_args.kwargs["limit"],
                    expected_count,
                )
                self.assertEqual(
                    research_sources.call_args.kwargs["fetch_article_text"],
                    not source_list_only,
                )

    def test_ask_story_streams_status_and_lists_sources_without_ai(self):
        async def collect(response, retrieve):
            iterator = response.body_iterator.__aiter__()
            first = await iterator.__anext__()
            first = first.decode("utf-8") if isinstance(first, bytes) else first
            self.assertIn("MIRA is analysing", first)
            retrieve.assert_not_called()
            return [
                first,
                *[
                    item.decode("utf-8") if isinstance(item, bytes) else item
                    async for item in iterator
                ],
            ]

        article = {
            "id": "pax-story",
            "title": "Pax Silica: A policy briefing",
            "summary": "A story about the Pax Silica initiative.",
            "source": "Original Publisher",
            "url": "https://publisher.example/pax-silica",
        }
        sources = [
            {
                "title": f"Pax Silica supporting report {index}",
                "source": f"Publisher {index}",
                "url": f"https://publisher{index}.example/pax-silica",
            }
            for index in (1, 2)
        ]
        with (
            patch.object(main.news, "get_article", return_value=article),
            patch.dict(main.news._cache, {"stored_loaded": False}),
            patch.object(main.news, "ensure_stored_cache_loaded") as ensure_stored,
            patch.object(main, "_retrieve", return_value=[]) as retrieve,
            patch.object(
                main.ask_story_research,
                "research_sources",
                return_value=(sources, "Two relevant sources found."),
            ),
            patch.object(main.news, "article_text") as article_text,
            patch.object(main.ask_story, "generate_stream") as generate_stream,
            patch.object(main, "_save_story_turn", return_value="conversation-1"),
        ):
            response = main.ask(
                main.AskIn(
                    article_id="pax-story",
                    messages=[main.Msg(
                        role="user",
                        content="Find 2 sources about this story",
                    )],
                ),
                uid=None,
                stream=True,
            )
            events = asyncio.run(collect(response, retrieve))

        decoded = [json.loads(event.removeprefix("data: ").strip()) for event in events]
        self.assertEqual(decoded[1]["text"], "MIRA is typing…")
        self.assertIn("https://publisher1.example/pax-silica", decoded[-1]["reply"])
        self.assertIn("https://publisher2.example/pax-silica", decoded[-1]["reply"])
        article_text.assert_not_called()
        generate_stream.assert_not_called()
        ensure_stored.assert_not_called()

    def test_sources_list_does_not_repeat_the_selected_story(self):
        article = {
            "title": "Selected story",
            "source": "Original Publisher",
            "url": "https://example.com/selected-story",
        }
        source = {
            "title": "Related reporting",
            "source": "Other Publisher",
            "url": "https://other.example/related-report",
        }

        reply = ask_story.append_sources(
            "Context from [ARTICLE], supported by [S1].",
            [source],
            include_all_sources=True,
        )

        self.assertNotIn(article["url"], reply)
        self.assertNotIn("Read selected article", reply)
        self.assertIn(source["url"], reply)

    def test_research_deduplicates_publishers_and_uses_extracted_text(self):
        related = [
            {
                "title": "Mindanao Avenue lane expansion Reuters report",
                "source": "Reuters",
                "url": "https://www.reuters.com/story-a",
                "summary": "DPWH Mindanao Avenue lane expansion Reuters excerpt",
            },
            {
                "title": "Another Mindanao Avenue lane expansion report",
                "source": "Reuters",
                "url": "https://www.reuters.com/story-b",
                "summary": "Duplicate publisher",
            },
        ]
        live = [
            {
                "title": f"Mindanao Avenue lane expansion report {index}",
                "source": f"Publisher {index}",
                "url": f"https://{domain}/story",
                "published": "2026-11-21",
                "summary": f"DPWH Mindanao Avenue lane expansion excerpt {index}",
                "domain": domain,
            }
            for index, domain in enumerate(
                ("apnews.com", "bbc.com", "dw.com", "france24.com"),
                start=1,
            )
        ]
        with patch.object(
            ask_story_research, "_google_news_candidates", return_value=live
        ), patch.object(
            ask_story_research,
            "_fetch_article_text",
            side_effect=lambda source: f"Full text from {source['domain']}",
        ):
            sources, disclosure = ask_story_research.research_sources(
                {"title": "Mindanao Avenue lane expansion"},
                "Write a comprehensive article",
                related,
                limit=5,
            )

        self.assertEqual(len(sources), 5)
        self.assertEqual(len({source["domain"] for source in sources}), 5)
        self.assertTrue(all(source["article_text"] for source in sources))
        self.assertIn("5 distinct", disclosure)

    def test_source_list_reuses_captured_articles_without_downloading_pages(self):
        article = {
            "title": "Pax Silica policy briefing",
            "url": "https://www.reuters.com/world/pax-silica-selected",
            "summary": "The selected story describes the Pax Silica initiative.",
        }
        related = [{
            "id": "pax-support",
            "title": "Pax Silica coverage in the Philippines",
            "source": "Reuters",
            "url": "https://www.rappler.com/news/pax-silica",
            "image": "https://www.rappler.com/tachyon/2026/11/pax-silica.jpg",
            "published": "2026-11-20",
            "summary": "Coverage describes the Pax Silica initiative and its impact in the Philippines.",
        }]
        with (
            patch.object(ask_story_research, "_google_news_candidates") as search,
            patch.object(ask_story_research, "_fetch_article_text") as fetch,
        ):
            sources, _disclosure = ask_story_research.research_sources(
                article,
                "Find 1 source about Pax Silica",
                related,
                limit=1,
                fetch_article_text=False,
            )

        search.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["retrieval_origin"], "captured")
        self.assertEqual(sources[0]["url"], related[0]["url"])
        self.assertEqual(sources[0]["image"], related[0]["image"])
        self.assertEqual(sources[0]["published"], related[0]["published"])
        self.assertEqual(sources[0]["article_text"], "")

    def test_source_list_external_search_uses_bounded_network_timeouts(self):
        with patch.object(
            ask_story_research, "_google_news_candidates", return_value=[]
        ) as search:
            ask_story_research.research_sources(
                {"title": "Pax Silica policy briefing"},
                "Find 2 sources about Pax Silica",
                [],
                limit=2,
                fetch_article_text=False,
            )

        self.assertTrue(search.call_args_list)
        self.assertTrue(all(
            call.kwargs["timeout"] <= 1.34
            and call.kwargs["resolve_timeout"] <= 1.34
            for call in search.call_args_list
        ))

    def test_source_references_identify_external_results(self):
        reply = ask_story.append_sources(
            "Relevant source.",
            [{
                "title": "Pax Silica report",
                "source": "Philippine Daily Inquirer",
                "url": "https://globalnation.inquirer.net/pax-silica",
                "image": "https://www.inquirer.net/images/pax-silica.jpg",
                "retrieval_origin": "external",
            }],
            include_all_sources=True,
        )

        self.assertIn("Newly retrieved externally", reply)
        self.assertIn("[Pax Silica report — Philippine Daily Inquirer]", reply)
        self.assertIn("![Pax Silica report thumbnail]", reply)
        self.assertIn(
            "https://www.inquirer.net/images/pax-silica.jpg",
            reply,
        )
        self.assertIn(
            "- [S1]\n"
            "  ![Pax Silica report thumbnail]"
            "(https://www.inquirer.net/images/pax-silica.jpg)\n"
            "  [Pax Silica report — Philippine Daily Inquirer]"
            "(https://globalnation.inquirer.net/pax-silica)",
            reply,
        )
        self.assertIn("https://globalnation.inquirer.net/pax-silica", reply)

    def test_research_retries_with_headline_when_focused_search_is_sparse(self):
        def search(query):
            if query == "Mindanao Avenue lane expansion effects students":
                return [{
                    "title": "Mindanao Avenue lane expansion focused result",
                    "source": "Reuters",
                    "url": "https://reuters.com/story",
                    "published": None,
                    "summary": "DPWH Mindanao Avenue lane expansion has enough detail to serve as a useful research source.",
                    "domain": "reuters.com",
                }]
            return [
                {
                    "title": f"Mindanao Avenue lane expansion headline result {index}",
                    "source": domain,
                    "url": f"https://{domain}/story",
                    "published": None,
                    "summary": f"Mindanao Avenue lane expansion result {index} has enough detail to serve as a useful research source.",
                    "domain": domain,
                }
                for index, domain in enumerate(
                    ("apnews.com", "bbc.com", "dw.com", "france24.com"),
                    start=1,
                )
            ]

        with patch.object(
            ask_story_research, "_google_news_candidates", side_effect=search
        ) as search_mock, patch.object(
            ask_story_research, "_fetch_article_text", return_value=""
        ):
            sources, disclosure = ask_story_research.research_sources(
                {"title": "Mindanao Avenue lane expansion"},
                "effects students",
                [],
                limit=5,
            )

        self.assertEqual(
            search_mock.call_args_list[0].args,
            ("Mindanao Avenue lane expansion effects students",),
        )
        self.assertEqual(
            search_mock.call_args_list[1].args,
            ("Mindanao Avenue lane expansion",),
        )
        self.assertEqual(len(sources), 5)
        self.assertEqual(len({source["domain"] for source in sources}), 5)
        self.assertIn("5 distinct", disclosure)

    def test_external_source_fallback_is_bounded_and_cached(self):
        candidate = {
            "id": "pax-source",
            "title": "Pax Silica report discusses policy",
            "source": "Reuters",
            "url": "https://www.reuters.com/world/pax-silica",
            "summary": "Pax Silica policy and the Philippines.",
            "domain": "reuters.com",
            "retrieval_origin": "external",
        }
        with (
            patch.dict(ask_story_research._SOURCE_CACHE, {}, clear=True),
            patch.object(
                ask_story_research,
                "_google_news_candidates",
                return_value=[candidate],
            ) as search,
        ):
            first = ask_story_research.external_sources("Pax Silica", limit=1)
            second = ask_story_research.external_sources("Pax Silica", limit=1)

        self.assertEqual(
            search.call_args_list,
            [
                call(
                    "Pax Silica", limit=24, timeout=1.2, resolve_timeout=1.0
                ),
                call(
                    "Pax Silica Philippines",
                    limit=24,
                    timeout=1.2,
                    resolve_timeout=1.0,
                ),
            ],
        )
        self.assertEqual(first, second)
        self.assertEqual(first[0]["url"], candidate["url"])
        self.assertEqual(first[0]["retrieval_origin"], "external")

    def test_source_lists_fill_requested_count_from_repeat_publishers(self):
        article = {
            "title": "Pax Silica policy briefing",
            "url": "https://www.bbc.com/news/selected-story",
        }
        related = [
            {
                "id": f"pax-{index}",
                "title": f"Pax Silica report {index}",
                "source": publisher,
                "url": f"https://{domain}/pax-silica-{index}",
                "summary": "Coverage of Pax Silica policy in the Philippines.",
            }
            for index, (publisher, domain) in enumerate((
                ("Reuters", "reuters.com"),
                ("AP News", "apnews.com"),
                ("Reuters", "reuters.com"),
                ("AP News", "apnews.com"),
                ("Reuters", "reuters.com"),
            ), start=1)
        ]
        with (
            patch.object(ask_story_research, "_google_news_candidates", return_value=[]),
            patch.object(ask_story_research, "_fetch_article_text", return_value=""),
        ):
            sources, _disclosure = ask_story_research.research_sources(
                article,
                "Find 5 sources about Pax Silica",
                related,
                limit=5,
                fetch_article_text=False,
            )

        self.assertEqual(len(sources), 5)
        self.assertEqual(
            [source["domain"] for source in sources[:2]],
            ["reuters.com", "apnews.com"],
        )

    def test_research_uses_broader_headline_terms_if_other_searches_are_sparse(self):
        headline = "Trump claims PH to buy farm energy goods from US; Marcos clarifies"

        def result(domain):
            return {
                "title": f"Trump Philippines energy farm Marcos report from {domain}",
                "source": domain,
                "url": f"https://{domain}/story",
                "published": None,
                "summary": f"Trump Philippines energy farm Marcos report from {domain} has enough detail to serve as a useful research source.",
                "domain": domain,
            }

        def search(query):
            if query == headline or query.startswith(f"{headline} "):
                return [result("reuters.com")]
            return [
                result(domain)
                for domain in ("apnews.com", "bbc.com", "dw.com", "france24.com")
            ]

        with patch.object(
            ask_story_research, "_google_news_candidates", side_effect=search
        ) as search_mock, patch.object(
            ask_story_research, "_fetch_article_text", return_value=""
        ):
            sources, disclosure = ask_story_research.research_sources(
                {"title": headline},
                "Write an article",
                [],
                limit=5,
            )

        self.assertEqual(search_mock.call_count, 2)
        self.assertEqual(
            search_mock.call_args_list[1].args,
            ("Trump Philippines US Marcos",),
        )
        self.assertEqual(len(sources), 5)
        self.assertIn("5 distinct", disclosure)

    def test_article_generation_and_research_intent_are_detected(self):
        self.assertEqual(
            ask_story.classify_task("Create a comprehensive article about this news"),
            "article_generation",
        )
        self.assertEqual(
            ask_story.classify_task("Investigate the people involved"),
            "research",
        )
        self.assertTrue(ask_story.requires_deep_research(
            "article_generation", "Write an article"
        ))

    def test_deep_article_prompt_requires_citations_and_disclosure(self):
        system = ask_story.story_system(
            {"title": "Selected story", "url": "https://example.com"},
            "Article text",
            [],
            research_disclosure="Only 2 sources were found.",
            deep_research=True,
            source_count=5,
        )

        self.assertIn("exact question, focus", system)
        self.assertIn("do not claim 5-source research", system)
        self.assertIn("[S1]", system)
        self.assertIn("Only 2 sources were found.", system)

    def test_quick_ask_story_prompt_labels_cached_summary_as_incomplete(self):
        system = ask_story.story_system(
            {"title": "Selected story", "url": "https://example.com"},
            "Cached summary text",
            [],
            article_text_is_summary=True,
        )

        self.assertIn("Cached article summary:\nCached summary text", system)
        self.assertIn("not the full article", system)


if __name__ == "__main__":
    unittest.main()
