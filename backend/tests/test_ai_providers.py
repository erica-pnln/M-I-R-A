import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import types

from app import ai, config, providers


class ProviderTests(unittest.TestCase):
    def setUp(self):
        providers.reset_health()
        with ai._response_cache_lock:
            ai._response_cache.clear()
        self.environment = patch.dict(os.environ, {
            "XAI_API_KEY": "test-key",
            "XAI_MODEL": "text-model",
            "XAI_VISION_MODEL": "vision-model",
            "AI_PROVIDER_PRIORITY": "gemini,xai,huggingface",
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_retired_gemini_model_maps_to_valid_flash_lite_id(self):
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-2.5-flash"}):
            self.assertEqual(
                config._gemini_model("GEMINI_MODEL", config.DEFAULT_GEMINI_MODEL),
                "gemini-3.5-flash-lite",
            )
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-3.8-flash"}):
            self.assertEqual(
                config._gemini_model("GEMINI_MODEL", config.DEFAULT_GEMINI_MODEL),
                "gemini-3.8-flash",
            )

    def test_only_vision_models_accept_image_contents(self):
        image = types.Part.from_bytes(data=b"image", mime_type="image/webp")
        contents = [types.Content(role="user", parts=[image])]

        candidates = providers.models_for("image_analysis", contents)

        self.assertEqual([model.model for model in candidates], ["vision-model"])

    def test_article_generation_with_images_only_selects_vision_models(self):
        image = types.Part.from_bytes(data=b"image", mime_type="image/png")
        contents = [types.Content(role="user", parts=[image])]

        candidates = providers.models_for("article_generation", contents)

        self.assertEqual([model.model for model in candidates], ["vision-model"])

    def test_non_image_files_are_not_sent_to_openai_compatible_models(self):
        pdf = types.Part.from_bytes(data=b"pdf", mime_type="application/pdf")
        contents = [types.Content(role="user", parts=[pdf])]

        self.assertEqual(providers.models_for("general_chat", contents), [])

    def test_cost_cap_excludes_models_without_known_cost_or_over_the_cap(self):
        os.environ["XAI_MODEL_COST_PER_1K_TOKENS"] = "0.25"
        os.environ["XAI_VISION_MODEL_COST_PER_1K_TOKENS"] = "0.8"
        os.environ["AI_MAX_COST_PER_1K_TOKENS"] = "0.5"

        candidates = providers.models_for("general_chat", "Question")

        self.assertEqual([model.model for model in candidates], ["text-model"])

    def test_cooldown_skips_an_unavailable_model(self):
        providers.record_health("xai:text-model", healthy=False, cooldown_seconds=30)

        candidates = providers.models_for("general_chat", "Question")

        self.assertNotIn("text-model", [model.model for model in candidates])

    def test_rate_limit_and_quota_are_fallback_errors_but_auth_is_not(self):
        self.assertEqual(providers._failure_from_response(429, "").category, "rate_limit")
        self.assertEqual(
            providers._failure_from_response(429, "quota exhausted").category,
            "quota_exhausted",
        )
        self.assertIn("HTTP 400", str(providers._failure_from_response(400, "")))
        authentication = providers._failure_from_response(401, "")
        self.assertEqual(authentication.category, "authentication")
        self.assertFalse(authentication.retryable)
        self.assertFalse(providers._failure_from_response(400, "").retryable)

    def test_external_provider_handles_requests_without_a_gemini_client(self):
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        with patch.object(providers, "sb", None), patch.object(
            providers, "generate", return_value=("xAI response", {})
        ) as generate:
            result = ai._generate_content(
                None, model="unused", contents="Question",
                config=config, task="general_chat",
            )

        self.assertEqual(result.text, "xAI response")
        self.assertEqual(generate.call_args.args[0].model, "text-model")

    def test_authentication_error_stops_without_trying_another_provider(self):
        os.environ["HF_TOKEN"] = "another-test-key"
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        failure = providers.ProviderFailure(
            "authentication", "Provider authentication failed."
        )
        with patch.object(providers, "sb", None), patch.object(
            providers, "generate", side_effect=failure
        ) as generate:
            with self.assertRaises(ai.AIUnavailable):
                ai._generate_content(
                    None, model="unused", contents="Question",
                    config=config, task="general_chat",
                )

        self.assertEqual(generate.call_count, 1)

    def test_invalid_request_tries_next_compatible_external_model(self):
        os.environ["HF_TOKEN"] = "hf-test-key"
        rejected = providers.ProviderFailure(
            "invalid_request", "Provider rejected the request (HTTP 400).",
            status_code=400,
        )
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        with patch.object(providers, "sb", None), patch.object(
            providers, "generate", side_effect=[
                rejected, ("Fallback response", {}),
            ]
        ) as generate:
            result = ai._generate_content(
                None, model="unused", contents="Question",
                config=config, task="general_chat",
            )

        self.assertEqual(result.text, "Fallback response")
        self.assertEqual(generate.call_count, 2)

    def test_gemini_image_rejection_tries_an_alternate_model(self):
        rejected = ai.errors.APIError.__new__(ai.errors.APIError)
        Exception.__init__(rejected, "invalid image request")
        rejected.code = 400
        rejected.status = "INVALID_ARGUMENT"
        rejected.details = {"message": "invalid image request"}

        class FakeModels:
            calls = 0

            def generate_content_stream(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise rejected
                return iter([SimpleNamespace(text="Gemini fallback", candidates=[])])

        models = FakeModels()
        client = SimpleNamespace(models=models)
        image = types.Part.from_bytes(data=b"image", mime_type="image/jpeg")
        contents = [types.Content(role="user", parts=[image])]
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        with patch.object(providers, "sb", None), patch.object(
            providers, "generate_stream"
        ) as generate_stream:
            result = list(ai._generate_content_stream(
                client,
                model="unused",
                contents=contents,
                config=config,
                task="image_analysis",
            ))

        self.assertEqual(result, ["Gemini fallback"])
        self.assertEqual(models.calls, 2)
        generate_stream.assert_not_called()

    def test_configured_provider_priority_applies_to_streaming_and_non_streaming(self):
        os.environ["AI_PROVIDER_PRIORITY"] = "xai,gemini,huggingface"
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        client = type("Client", (), {
            "models": type("Models", (), {
                "generate_content": lambda *args, **kwargs: self.fail(
                    "Gemini should not run before xAI at this priority."
                )
            })()
        })()
        with patch.object(providers, "sb", None), patch.object(
            providers, "generate", return_value=("xAI response", {})
        ):
            result = ai._generate_content(
                client, model="unused", contents="Question",
                config=config, task="general_chat",
            )
        self.assertEqual(result.text, "xAI response")

        with patch.object(providers, "sb", None), patch.object(
            providers, "generate_stream", return_value=iter(["xAI", " stream"])
        ):
            result = list(ai._generate_content_stream(
                client, model="unused", contents="Question",
                config=config, task="general_chat",
            ))
        self.assertEqual(result, ["xAI", " stream"])

    def test_temporary_failure_uses_bounded_backoff_then_falls_back(self):
        os.environ["HF_TOKEN"] = "hf-test-key"
        os.environ["AI_MAX_RETRIES_PER_MODEL"] = "1"
        failure = providers.ProviderFailure(
            "temporary_unavailable", "Provider is temporarily unavailable.",
            retryable=True, status_code=503,
        )
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        with (
            patch.object(providers, "sb", None),
            patch.object(providers, "generate", side_effect=[
                failure, failure, ("Hugging Face response", {}),
            ]) as generate,
            patch.object(ai.time, "sleep") as sleep,
        ):
            result = ai._generate_content(
                None, model="unused", contents="Question",
                config=config, task="general_chat",
            )

        self.assertEqual(result.text, "Hugging Face response")
        self.assertEqual(generate.call_count, 3)
        sleep.assert_called_once_with(0.5)

    def test_temporary_failure_moves_to_next_provider_without_same_model_retry(self):
        os.environ["HF_TOKEN"] = "hf-test-key"
        failure = providers.ProviderFailure(
            "temporary_unavailable", "Provider is temporarily unavailable.",
            retryable=True, status_code=503,
        )
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        with (
            patch.object(providers, "sb", None),
            patch.object(providers, "generate", side_effect=[
                failure, ("Hugging Face response", {}),
            ]) as generate,
            patch.object(ai.time, "sleep") as sleep,
        ):
            result = ai._generate_content(
                None, model="unused", contents="Question",
                config=config, task="general_chat",
            )

        self.assertEqual(result.text, "Hugging Face response")
        self.assertEqual(generate.call_count, 2)
        sleep.assert_not_called()

    def test_stream_skips_gemini_fallback_models_for_external_provider(self):
        overloaded = ai.errors.APIError.__new__(ai.errors.APIError)
        Exception.__init__(overloaded, "temporarily unavailable")
        overloaded.code = 503
        overloaded.status = "UNAVAILABLE"
        overloaded.details = {"message": "temporarily unavailable"}

        class FakeModels:
            calls = 0

            def generate_content_stream(self, **kwargs):
                self.calls += 1
                raise overloaded

        client = SimpleNamespace(models=FakeModels())
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        with patch.object(providers, "sb", None), patch.object(
            providers, "generate_stream", return_value=iter(["External response"])
        ) as generate_stream:
            result = list(ai._generate_content_stream(
                client,
                model="unused",
                contents="Question",
                config=config,
                task="general_chat",
            ))

        self.assertEqual(result, ["External response"])
        self.assertEqual(client.models.calls, 1)
        generate_stream.assert_called_once()

    def test_gemini_server_error_fails_over_before_another_gemini_model(self):
        overloaded = ai.errors.APIError.__new__(ai.errors.APIError)
        Exception.__init__(overloaded, "temporarily unavailable")
        overloaded.code = 503
        overloaded.status = "UNAVAILABLE"
        overloaded.details = {"message": "temporarily unavailable"}

        class FakeModels:
            calls = 0

            def generate_content(self, **kwargs):
                self.calls += 1
                raise overloaded

        client = SimpleNamespace(models=FakeModels())
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        with patch.object(providers, "sb", None), patch.object(
            providers, "generate", return_value=("External response", {})
        ) as generate:
            result = ai._generate_content(
                client,
                model="unused",
                contents="Question",
                config=config,
                task="general_chat",
            )

        self.assertEqual(result.text, "External response")
        self.assertEqual(client.models.calls, 1)
        generate.assert_called_once()

    def test_article_summaries_use_a_bounded_response_cache(self):
        class FakeModels:
            calls = 0

            def generate_content(self, **kwargs):
                self.calls += 1
                return SimpleNamespace(text="Cached summary")

        models = FakeModels()
        client = SimpleNamespace(models=models)
        config = types.GenerateContentConfig(system_instruction="Be accurate.")
        with patch.object(providers, "sb", None):
            first = ai._generate_content(
                client, model="test-model", contents="Article text",
                config=config, task="news_summarization",
            )
            second = ai._generate_content(
                client, model="test-model", contents="Article text",
                config=config, task="news_summarization",
            )

        self.assertEqual(first.text, "Cached summary")
        self.assertEqual(second.text, "Cached summary")
        self.assertEqual(models.calls, 1)

    def test_article_generation_has_a_larger_chat_output_budget(self):
        class FakeModels:
            config = None

            def generate_content(self, **kwargs):
                self.config = kwargs["config"]
                return SimpleNamespace(text="Article draft")

        models = FakeModels()
        client = SimpleNamespace(models=models)
        with patch.object(ai, "_client", client), patch.object(providers, "sb", None):
            ai.chat(
                [{"role": "user", "content": "Write an article."}],
                task="article_generation",
            )

        self.assertEqual(models.config.max_output_tokens, ai._ARTICLE_OUTPUT_TOKENS)


if __name__ == "__main__":
    unittest.main()
