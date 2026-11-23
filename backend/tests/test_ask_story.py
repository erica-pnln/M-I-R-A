import os
import unittest
from unittest.mock import patch

from app import ask_story


class AskStoryTests(unittest.TestCase):
    def setUp(self):
        ask_story.reset_health()
        self.environment = patch.dict(os.environ, {
            "ASK_STORY_HF_TOKEN": "ask-story-hf-test",
            "ASK_STORY_HF_PRIMARY_MODEL": "primary/hf",
            "ASK_STORY_HF_FALLBACK_MODELS": "fallback/hf-one,fallback/hf-two",
            "ASK_STORY_XAI_API_KEY": "ask-story-xai-test",
            "ASK_STORY_XAI_MODEL": "grok-test",
            "ASK_STORY_PROVIDER_PRIORITY": "huggingface,xai",
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_does_not_use_mira_chat_credentials(self):
        os.environ["HF_TOKEN"] = "shared-chat-token"
        os.environ["XAI_API_KEY"] = "shared-chat-xai"
        os.environ["GEMINI_API_KEY"] = "shared-chat-gemini"

        models = ask_story.configured_models()

        self.assertTrue(models)
        self.assertTrue(all(model.api_key.startswith("ask-story-") for model in models))
        self.assertEqual(
            [model.model for model in models],
            ["primary/hf", "fallback/hf-one", "fallback/hf-two", "grok-test"],
        )

    def test_cooling_down_skips_unavailable_model(self):
        models = ask_story.configured_models()
        ask_story._record_health(models[0], "rate_limit", 429)

        available = ask_story.models_for_task("story_chat")

        self.assertNotIn("primary/hf", [model.model for model in available])
        self.assertIn("fallback/hf-one", [model.model for model in available])

    def test_task_classification(self):
        self.assertEqual(
            ask_story.classify_task("Write a complete article about this story"),
            "article_generation",
        )
        self.assertEqual(
            ask_story.classify_task("Explain what this means"),
            "story_explanation",
        )
        self.assertEqual(
            ask_story.classify_task("Summarize this article"),
            "news_summarization",
        )

    def test_quick_ask_story_tasks_use_a_smaller_output_budget(self):
        spec = ask_story.AskStoryModel(
            provider="test",
            model="test-model",
            api_key="test-key",
            base_url="https://example.test/v1",
            tasks=ask_story.TASKS,
        )

        self.assertEqual(
            ask_story._request(spec, [], "", "story_chat")["max_tokens"],
            512,
        )
        self.assertEqual(
            ask_story._request(spec, [], "", "research")["max_tokens"],
            900,
        )
        self.assertEqual(
            ask_story._request(spec, [], "", "article_generation")["max_tokens"],
            1800,
        )

    def test_gemini_is_dedicated_to_ask_story(self):
        os.environ["GEMINI_API_KEY"] = "mira-chat-key"
        os.environ["ASK_STORY_GEMINI_API_KEY"] = "ask-story-gemini-key"
        os.environ["ASK_STORY_GEMINI_PRIMARY_MODEL"] = "gemini-3.5-flash-lite"
        os.environ["ASK_STORY_GEMINI_FALLBACK_MODELS"] = "gemini-flash-lite-latest"

        gemini_models = [
            model for model in ask_story.configured_models()
            if model.provider == "gemini"
        ]

        self.assertEqual(
            [model.model for model in gemini_models],
            ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"],
        )
        self.assertTrue(all(
            model.api_key == "ask-story-gemini-key"
            for model in gemini_models
        ))

    def test_payment_required_is_quota_error_and_fallbackable(self):
        failure = ask_story._failure(402, "insufficient credits")

        self.assertEqual(failure.category, "quota_exhausted")
        self.assertTrue(failure.retryable)

    def test_invalid_model_request_moves_to_next_model(self):
        rejected = ask_story.AskStoryFailure(
            "invalid_request",
            "The Ask Story provider rejected the request (HTTP 400).",
            status_code=400,
        )
        with patch.object(ask_story, "sb", None), patch.object(
            ask_story.httpx,
            "post",
            side_effect=[rejected, rejected, rejected, rejected, rejected, rejected],
        ):
            with self.assertRaises(ask_story.AskStoryFailure) as raised:
                ask_story.generate(
                    [{"role": "user", "content": "Question"}],
                    "System",
                    task="story_chat",
                    article_id="article-1",
                )

        self.assertEqual(raised.exception.category, "providers_unavailable")

    def test_authentication_error_does_not_fall_back(self):
        failure = ask_story.AskStoryFailure(
            "authentication", "authentication failed", status_code=401
        )
        with patch.object(ask_story, "sb", None), patch.object(
            ask_story.httpx, "post", side_effect=failure
        ):
            with self.assertRaises(ask_story.AskStoryFailure) as raised:
                ask_story.generate(
                    [{"role": "user", "content": "Question"}],
                    "System",
                    task="story_chat",
                    article_id="article-1",
                )

        self.assertEqual(raised.exception.category, "authentication")


if __name__ == "__main__":
    unittest.main()
