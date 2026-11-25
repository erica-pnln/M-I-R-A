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

    def test_invalid_request_cooldown_is_task_scoped_and_keeps_only_model_usable(self):
        model = ask_story.AskStoryModel(
            "test", "text-model", "key", "https://example.test/v1",
            ("story_chat", "story_explanation"),
        )
        ask_story._record_health(model, "invalid_request", 400, task="story_chat")
        with patch.object(ask_story, "configured_models", return_value=[model]):
            self.assertEqual(ask_story.models_for_task("story_chat"), [model])
            self.assertEqual(ask_story.models_for_task("story_explanation"), [model])

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

    def test_stream_continues_partial_answer_with_fallback_model(self):
        first = ask_story.AskStoryModel(
            "test", "broken-model", "key", "https://example.test/v1",
            ("story_chat",),
        )
        fallback = ask_story.AskStoryModel(
            "test", "fallback-model", "key", "https://example.test/v1",
            ("story_chat",),
        )
        rejected = ask_story.AskStoryFailure(
            "invalid_request", "Provider rejected the request (HTTP 400).",
            status_code=400,
        )

        class FakeResponse:
            is_error = False

            def __init__(self, *, partial=False):
                self.partial = partial

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def iter_lines(self):
                if self.partial:
                    yield 'data: {"choices":[{"delta":{"content":"The lead "}}]}'
                    raise rejected
                yield 'data: {"choices":[{"delta":{"content":"Next point."}}]}'
                yield "data: [DONE]"

        responses = [FakeResponse(partial=True), FakeResponse()]
        messages = [{"role": "user", "content": "Explain the inverted pyramid."}]
        with (
            patch.object(ask_story, "models_for_task", return_value=[first, fallback]),
            patch.object(ask_story, "sb", None),
            patch.object(
                ask_story.httpx, "stream", side_effect=responses
            ) as stream_request,
        ):
            result = list(ask_story.generate_stream(
                messages, "System", task="story_chat", article_id="story-id"
            ))

        self.assertEqual(
            result,
            [("The lead ", first.model), ("Next point.", fallback.model)],
        )
        fallback_messages = stream_request.call_args_list[1].kwargs["json"]["messages"]
        self.assertEqual(fallback_messages[-2]["role"], "assistant")
        self.assertIn("The lead", fallback_messages[-2]["content"])
        self.assertIn("Continue the answer", fallback_messages[-1]["content"])

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
