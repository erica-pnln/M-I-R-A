import unittest
from unittest.mock import patch

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
            patch.object(main.news, "ensure_stored_cache_loaded"),
            patch.object(main, "_retrieve", return_value=[]),
            patch.object(
                main.news,
                "search_discovery",
                return_value={"articles": live_articles, "source_errors": []},
            ) as search,
            patch.object(main.news, "_decode_google_news_urls", return_value={}),
            patch.object(
                main.intelligence, "fast_search",
                return_value=(live_articles, None),
            ),
        ):
            result = main._research_context(messages, "auto")

        self.assertIn("pax", search.call_args.args[0].casefold())
        self.assertIn("silica", search.call_args.args[0].casefold())
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
                patch.object(
                    main, "_retrieve", return_value=[]
                ) as retrieve,
                patch.object(
                    main.ask_story_research,
                    "research_sources",
                    return_value=([], "Research retrieval found no sources."),
                ) as research_sources,
                patch.object(main, "_ai_language_instruction", return_value=""),
                patch.object(main.ask_story, "generate", return_value=("Answer", "model")),
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

            self.assertEqual(retrieve.call_args.kwargs["limit"], expected_count)
            get_article.assert_called_once_with(
                "story-id", enrich_image=False
            )
            self.assertEqual(research_sources.called, deep_research)
            self.assertEqual(article_text.called, deep_research)
            if deep_research:
                self.assertEqual(
                    research_sources.call_args.kwargs["limit"],
                    expected_count,
                )

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
