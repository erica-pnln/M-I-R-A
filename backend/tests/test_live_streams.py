import json
import unittest

from app.main import _current_youtube_stream, _youtube_channel_artwork


class FakeResponse:
    def __init__(self, player, initial_data=None):
        self.text = (
            f"var ytInitialData = {json.dumps(initial_data or {})};"
            f"var ytInitialPlayerResponse = {json.dumps(player)};"
        )

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, player, initial_data=None):
        self.response = FakeResponse(player, initial_data)

    async def get(self, _url):
        return self.response


def player_response(*, is_live_now, playability="OK"):
    return {
        "playabilityStatus": {"status": playability},
        "videoDetails": {
            "videoId": "abcdefghijk",
            "title": "Current broadcaster stream",
            "isLiveContent": True,
            "thumbnail": {"thumbnails": [
                {"url": "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg", "width": 320},
                {"url": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg", "width": 480},
                {"url": "https://i.ytimg.com/vi/abcdefghijk/sddefault.jpg", "width": 640},
                {"url": "https://i.ytimg.com/vi/abcdefghijk/maxresdefault.jpg", "width": 1280},
            ]},
        },
        "microformat": {
            "playerMicroformatRenderer": {
                "liveBroadcastDetails": {"isLiveNow": is_live_now},
            },
        },
    }


class LiveStreamTests(unittest.IsolatedAsyncioTestCase):
    def test_uses_only_the_official_channel_avatar_for_inactive_preview(self):
        page_data = {
            "videoOwnerRenderer": {
                "channelAvatar": {
                    "thumbnails": [{
                        "url": "https://yt3.ggpht.com/example=s88-c-k-c0x00ffffff-no-rj",
                        "width": 88,
                    }],
                },
                "channelEndpoint": {
                    "browseEndpoint": {"canonicalBaseUrl": "/@example"},
                },
            },
            "otherOwnerRenderer": {
                "channelAvatar": {
                    "thumbnails": [{
                        "url": "https://yt3.ggpht.com/other=s88-c-k-c0x00ffffff-no-rj",
                        "width": 88,
                    }],
                },
                "channelEndpoint": {
                    "browseEndpoint": {"canonicalBaseUrl": "/@other"},
                },
            },
        }

        image = _youtube_channel_artwork(
            f"var ytInitialData = {json.dumps(page_data)};",
            "https://www.youtube.com/@example/live",
        )

        self.assertEqual(
            image,
            "https://yt3.googleusercontent.com/example=s512-c-k-c0x00ffffff-no-rj",
        )
        self.assertEqual(
            _youtube_channel_artwork(
                f"var ytInitialData = {json.dumps(page_data)};",
                "https://www.youtube.com/@unrelated/live",
            ),
            "",
        )

    def test_reads_channel_metadata_renderer_avatar(self):
        page_data = {
            "metadata": {
                "channelMetadataRenderer": {
                    "externalId": "UCexample",
                    "vanityChannelUrl": "https://www.youtube.com/@example",
                    "avatar": {
                        "thumbnails": [{
                            "url": "https://yt3.googleusercontent.com/example=s900-c-k-c0x00ffffff-no-rj",
                            "width": 900,
                        }],
                    },
                },
            },
        }

        image = _youtube_channel_artwork(
            f"var ytInitialData = {json.dumps(page_data)};",
            "https://www.youtube.com/@example/live",
        )

        self.assertEqual(
            image,
            "https://yt3.googleusercontent.com/example=s512-c-k-c0x00ffffff-no-rj",
        )

    async def test_keeps_channel_artwork_when_player_metadata_is_unavailable(self):
        page_data = {
            "videoOwnerRenderer": {
                "channelAvatar": {
                    "thumbnails": [{
                        "url": "https://yt3.ggpht.com/example=s88-c-k-c0x00ffffff-no-rj",
                        "width": 88,
                    }],
                },
                "channelEndpoint": {
                    "browseEndpoint": {"canonicalBaseUrl": "/@example"},
                },
            },
        }

        class ChannelPageClient:
            async def get(self, _url):
                response = FakeResponse({})
                response.text = (
                    f"var ytInitialData = {json.dumps(page_data)};"
                    "var ytInitialPlayerResponse = ;"
                )
                return response

        result = await _current_youtube_stream(
            ChannelPageClient(),
            {
                "publisher": "Example News",
                "title": "Example News Live",
                "source_url": "https://www.youtube.com/@example/live",
            },
        )

        self.assertEqual(
            result,
            {
                "image": "https://yt3.googleusercontent.com/example=s512-c-k-c0x00ffffff-no-rj",
                "channel_image": "https://yt3.googleusercontent.com/example=s512-c-k-c0x00ffffff-no-rj",
            },
        )

    async def test_returns_exact_video_link_only_for_active_stream(self):
        page_data = {
            "metadata": {
                "channelMetadataRenderer": {
                    "externalId": "UCexample",
                    "vanityChannelUrl": "https://www.youtube.com/@example",
                    "avatar": {
                        "thumbnails": [{
                            "url": "https://yt3.googleusercontent.com/example=s900-c-k-c0x00ffffff-no-rj",
                            "width": 900,
                        }],
                    },
                },
            },
        }
        result = await _current_youtube_stream(
            FakeClient(player_response(is_live_now=True), initial_data=page_data),
            {
                "publisher": "Example News",
                "title": "Example News Live",
                "source_url": "https://www.youtube.com/@example/live",
            },
        )

        self.assertEqual(result["url"], "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(result["title"], "Current broadcaster stream")
        self.assertEqual(result["image"], "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg")
        self.assertEqual(
            result["channel_image"],
            "https://yt3.googleusercontent.com/example=s512-c-k-c0x00ffffff-no-rj",
        )
        self.assertTrue(result["is_live"])

    async def test_omits_scheduled_or_offline_streams(self):
        for player in (
            player_response(is_live_now=False),
            player_response(is_live_now=True, playability="LIVE_STREAM_OFFLINE"),
        ):
            with self.subTest(player=player["playabilityStatus"]["status"]):
                result = await _current_youtube_stream(
                    FakeClient(player),
                    {
                        "publisher": "Example News",
                        "title": "Example News Live",
                        "source_url": "https://www.youtube.com/@example/live",
                    },
                )
                self.assertIsNone(result)
