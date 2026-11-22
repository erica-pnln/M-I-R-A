import unittest
from unittest.mock import patch

from app import ask_story, ask_story_research


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

    def test_research_discloses_when_fewer_than_five_publishers_are_found(self):
        related = [
            {
                "title": f"Report {index}",
                "source": f"Publisher {index}",
                "url": f"https://{domain}/story",
                "summary": f"Evidence excerpt {index} with enough detail to serve as a retrieved source snippet.",
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
                {"title": "Selected story"},
                "Write a detailed article",
                related,
            )

        self.assertEqual(len(sources), 4)
        self.assertIn("only 4 distinct", disclosure)
        self.assertIn("do not claim that five sources", disclosure)
        self.assertEqual([source["id"] for source in sources], ["S1", "S2", "S3", "S4"])

    def test_research_deduplicates_publishers_and_uses_extracted_text(self):
        related = [
            {
                "title": "Reuters story",
                "source": "Reuters",
                "url": "https://www.reuters.com/story-a",
                "summary": "Reuters excerpt",
            },
            {
                "title": "Another Reuters story",
                "source": "Reuters",
                "url": "https://www.reuters.com/story-b",
                "summary": "Duplicate publisher",
            },
        ]
        live = [
            {
                "title": f"Story {index}",
                "source": f"Publisher {index}",
                "url": f"https://{domain}/story",
                "published": "2026-11-21",
                "summary": f"Excerpt {index}",
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
                {"title": "Selected story"},
                "Write a comprehensive article",
                related,
            )

        self.assertEqual(len(sources), 5)
        self.assertEqual(len({source["domain"] for source in sources}), 5)
        self.assertTrue(all(source["article_text"] for source in sources))
        self.assertIn("5 distinct", disclosure)

    def test_research_retries_with_headline_when_focused_search_is_sparse(self):
        def search(query):
            if query == "Selected story effects students":
                return [{
                    "title": "Focused result",
                    "source": "Reuters",
                    "url": "https://reuters.com/story",
                    "published": None,
                    "summary": "Focused result has enough detail to serve as a useful research source.",
                    "domain": "reuters.com",
                }]
            return [
                {
                    "title": f"Headline result {index}",
                    "source": domain,
                    "url": f"https://{domain}/story",
                    "published": None,
                    "summary": f"Headline result {index} has enough detail to serve as a useful research source.",
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
                {"title": "Selected story"},
                "effects students",
                [],
            )

        self.assertEqual(search_mock.call_args_list[0].args, ("Selected story effects students",))
        self.assertEqual(search_mock.call_args_list[1].args, ("Selected story",))
        self.assertEqual(len(sources), 5)
        self.assertEqual(len({source["domain"] for source in sources}), 5)
        self.assertIn("5 distinct", disclosure)

    def test_research_uses_broader_headline_terms_if_other_searches_are_sparse(self):
        headline = "Trump claims PH to buy farm energy goods from US; Marcos clarifies"

        def result(domain):
            return {
                "title": f"Report from {domain}",
                "source": domain,
                "url": f"https://{domain}/story",
                "published": None,
                "summary": f"Report from {domain} has enough detail to serve as a useful research source.",
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
        )

        self.assertIn("exact question, focus", system)
        self.assertIn("do not claim five-source research", system)
        self.assertIn("[S1]", system)
        self.assertIn("Only 2 sources were found.", system)


if __name__ == "__main__":
    unittest.main()
