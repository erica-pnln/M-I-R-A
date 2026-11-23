import unittest
from unittest.mock import AsyncMock, patch

from app import main, news
from app.media_sources import (
    LANGUAGES,
    RADIO_STATIONS,
    classify_news_source,
    classify_publisher,
    live_channels,
    podcast_categories,
)
from app.news import _article_matches_topic


class MediaSourceTests(unittest.TestCase):
    def test_radio_catalog_covers_requested_regional_stations_and_facets(self):
        names = {station["name"] for station in RADIO_STATIONS}
        self.assertTrue({
            "Aksyon Radyo Tacloban",
            "Bombo Radyo Tacloban",
            "Brigada News FM Tacloban",
            "iFM RMN Tacloban",
            "Aksyon Radyo Catbalogan",
            "Aksyon Radyo Catarman",
            "Radyo Pilipinas Calbayog",
            "Radyo Pilipinas Borongan",
            "Radyo Natin Calbayog",
            "FMR Tacloban",
            "Brigada News FM Ormoc",
            "DYHP RMN Cebu",
            "Aksyon Radyo Cebu",
            "Bombo Radyo Cebu",
            "Super Radyo Cebu",
            "Radyo Pilipinas Cebu",
            "Radyo Ronda Cebu",
            "Brigada News FM Cebu",
            "DYTR Tagbilaran",
            "RMN Butuan",
            "RMN Cagayan de Oro",
            "RMN Davao",
            "RMN General Santos",
            "RMN Iligan",
            "RMN Koronadal",
            "RMN Malaybalay",
            "RMN Pagadian",
            "RMN Surigao",
            "RMN Zamboanga",
            "DZRH",
            "GMA Super Radyo DZBB",
            "DWIZ",
            "DZXL RMN",
            "Radyo Pilipinas 1",
            "Radyo Pilipinas 2",
            "Radyo5 True FM",
            "Radyo Veritas",
            "DWWW",
            "Radyo Agila",
        }.issubset(names))
        station = next(item for item in RADIO_STATIONS if item["name"] == "Aksyon Radyo Tacloban")
        self.assertEqual(station["language"], "Waray")
        self.assertEqual(station["region"], "Eastern Visayas")
        self.assertEqual(station["province"], "Leyte")
        self.assertEqual(station["city"], "Tacloban")
        self.assertIn("Hiligaynon", LANGUAGES)
        self.assertIn("Ilocano", LANGUAGES)
        self.assertIn("Bicolano", LANGUAGES)

    def test_news_filters_match_publisher_language_and_location_not_unrelated_sources(self):
        story = {"source": "Aksyon Radyo Tacloban"}
        self.assertTrue(_article_matches_topic(story, "Aksyon Radyo"))
        self.assertTrue(_article_matches_topic(story, "Waray"))
        self.assertTrue(_article_matches_topic(story, "Eastern Visayas"))
        self.assertTrue(_article_matches_topic(story, "Tacloban"))
        self.assertFalse(_article_matches_topic({"source": "BBC News"}, "Waray"))

    def test_news_search_indexes_classified_language_and_location(self):
        articles = [
            {"id": "tacloban", "title": "Local radio update", "summary": "", "source": "Aksyon Radyo Tacloban", "section": "local", "url": "https://example.test/tacloban"},
            {"id": "world", "title": "World report", "summary": "", "source": "BBC News", "section": "international", "url": "https://example.test/world"},
        ]
        with (
            patch.dict(news._cache, {"items": articles, "stored_loaded": True}),
            patch.dict(news._search_cache, {}, clear=True),
            patch.object(news, "sb", None),
            patch.object(news, "_schedule_image_enrichment"),
            patch.object(
                news,
                "_pull_feeds",
                new=AsyncMock(return_value=[([], "Feed returned no entries")]),
            ),
        ):
            result = main.search_articles(
                q="Tacloban",
                section=None,
                topic=None,
                limit=1,
                offset=0,
                uid=None,
            )
        self.assertEqual(result["articles"][0]["id"], "tacloban")
        self.assertTrue(all("text" not in article for article in result["articles"]))

    def test_radio_catalog_does_not_claim_unverified_streams_are_live(self):
        channels = live_channels()
        self.assertTrue(channels)
        self.assertTrue(all(channel["is_live"] is False for channel in channels))
        self.assertTrue(all(not channel["url"] for channel in channels))
        tacloban = next(channel for channel in channels if channel["title"] == "Aksyon Radyo Tacloban")
        self.assertIn("Radio Broadcasters", tacloban["categories"])
        self.assertIn("Waray", tacloban["categories"])
        self.assertIn("Tacloban", tacloban["categories"])

    def test_radio_catalog_links_known_network_sources_and_brand_artwork(self):
        channels = live_channels()
        for network, host in (
            ("Aksyon Radyo", "mbc.com.ph"),
            ("Bombo Radyo", "bomboradyo.com"),
            ("Brigada News FM", "brigada.ph"),
            ("RMN", "rmn.ph"),
            ("DZRH", "dzrh.com.ph"),
        ):
            channel = next(item for item in channels if item["publisher"] == network)
            self.assertIn(host, channel["source_page_url"])
            self.assertIn(f"domain_url=https://{host}", channel["logo_url"])

    def test_podcast_filters_use_publisher_metadata_and_actual_episode_text(self):
        media = classify_publisher("DZRH")
        self.assertEqual(media["publisher"], "DZRH")
        self.assertIn("Radio Networks", media["categories"])
        categories = podcast_categories({
            "title": "DZRH News interview on current affairs in the Philippines",
            "publisher": "DZRH",
            "categories": media["categories"],
            "media": media,
        })
        self.assertIn("DZRH", categories)
        self.assertIn("Tagalog / Filipino", categories)
        self.assertIn("Interviews", categories)
        self.assertIn("Current Affairs", categories)
        self.assertIn("National News", categories)

    def test_unmatched_publishers_are_not_assigned_fabricated_station_metadata(self):
        self.assertIsNone(classify_news_source("Unknown Publisher"))
        self.assertIsNone(classify_publisher("Unknown Podcast"))


if __name__ == "__main__":
    unittest.main()
