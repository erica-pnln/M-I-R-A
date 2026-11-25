import atexit
import base64
import json
import logging
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Iterator

import httpx

from .db import sb

logger = logging.getLogger(__name__)

_health_lock = threading.Lock()
_cooldowns: dict[str, float] = {}
_TIMEOUT_SECONDS = max(1.0, float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "30")))
_http_client_lock = threading.Lock()
_http_client: httpx.Client | None = None
_usage_schema_warning_logged = False


def _get_http_client() -> httpx.Client:
    global _http_client
    with _http_client_lock:
        if _http_client is None:
            _http_client = httpx.Client()
        return _http_client


def close_http_client() -> None:
    global _http_client
    with _http_client_lock:
        client = _http_client
        _http_client = None
    if client is not None:
        client.close()


atexit.register(close_http_client)


class ProviderFailure(RuntimeError):
    def __init__(
        self,
        category: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    api_key: str
    base_url: str
    tasks: tuple[str, ...]
    vision: bool
    priority: int
    image_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp")
    cost_per_1k_tokens: float | None = None

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


def provider_rank(provider: str) -> int:
    order = [
        item.strip().lower()
        for item in os.getenv("AI_PROVIDER_PRIORITY", "gemini,xai,huggingface").split(",")
        if item.strip()
    ]
    try:
        return order.index(provider.lower())
    except ValueError:
        return len(order)


def _priority(provider: str, default: int) -> int:
    return provider_rank(provider) * 100 + default


def _cost(value, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        cost = float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderFailure("configuration", f"{name} must be a non-negative number.") from exc
    if not math.isfinite(cost) or cost < 0:
        raise ProviderFailure("configuration", f"{name} must be a non-negative number.")
    return cost


def _all_tasks() -> tuple[str, ...]:
    return (
        "general_chat",
        "story_chat",
        "image_analysis",
        "article_analysis",
        "news_summarization",
        "article_generation",
        "fact_checking",
        "research",
    )


def configured_models() -> list[ModelSpec]:
    specs: list[ModelSpec] = []
    raw_models = os.getenv("AI_MODELS_JSON", "").strip()
    if raw_models:
        try:
            configured = json.loads(raw_models)
        except json.JSONDecodeError as exc:
            raise ProviderFailure(
                "configuration", "AI_MODELS_JSON must contain a valid JSON array."
            ) from exc
        if not isinstance(configured, list):
            raise ProviderFailure("configuration", "AI_MODELS_JSON must contain a JSON array.")
        for index, item in enumerate(configured):
            if not isinstance(item, dict):
                raise ProviderFailure(
                    "configuration", "Each AI_MODELS_JSON entry must be an object."
                )
            provider = str(item.get("provider", "openai_compatible")).strip().lower()
            model = str(item.get("model", "")).strip()
            api_key_env = str(item.get("api_key_env", "")).strip()
            base_url = str(item.get("base_url", "")).strip()
            key = os.getenv(api_key_env, "").strip() if api_key_env else ""
            tasks = item.get("tasks", list(_all_tasks()))
            if not model or not base_url or not isinstance(tasks, list) or not key:
                continue
            image_types = item.get("image_types", ["image/jpeg", "image/png", "image/webp"])
            if not isinstance(image_types, list):
                raise ProviderFailure(
                    "configuration", "AI model image_types must be a JSON array."
                )
            specs.append(ModelSpec(
                provider=provider,
                model=model,
                api_key=key,
                base_url=base_url.rstrip("/"),
                tasks=tuple(str(task) for task in tasks),
                vision=bool(item.get("vision", False)),
                priority=_priority(provider, int(item.get("priority", index))),
                image_types=tuple(str(mime) for mime in image_types),
                cost_per_1k_tokens=_cost(
                    item.get("cost_per_1k_tokens"), "cost_per_1k_tokens"
                ),
            ))

    xai_key = os.getenv("XAI_API_KEY", "").strip()
    if xai_key:
        xai_base = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1").strip().rstrip("/")
        xai_tasks = _all_tasks()
        specs.append(ModelSpec(
            "xai", os.getenv("XAI_MODEL", "grok-3-mini").strip(), xai_key,
            xai_base, xai_tasks, False, _priority("xai", 0),
            cost_per_1k_tokens=_cost(
                os.getenv("XAI_MODEL_COST_PER_1K_TOKENS"),
                "XAI_MODEL_COST_PER_1K_TOKENS",
            ),
        ))
        vision_model = os.getenv("XAI_VISION_MODEL", "grok-2-vision-1212").strip()
        if vision_model:
            specs.append(ModelSpec(
                "xai", vision_model, xai_key, xai_base, xai_tasks, True,
                _priority("xai", 1),
                cost_per_1k_tokens=_cost(
                    os.getenv("XAI_VISION_MODEL_COST_PER_1K_TOKENS"),
                    "XAI_VISION_MODEL_COST_PER_1K_TOKENS",
                ),
            ))

    hf_key = os.getenv("HF_TOKEN", "").strip()
    if hf_key:
        hf_base = os.getenv(
            "HF_BASE_URL", "https://router.huggingface.co/v1"
        ).strip().rstrip("/")
        hf_tasks = _all_tasks()
        specs.append(ModelSpec(
            "huggingface",
            os.getenv("HF_MODEL", "CohereLabs/tiny-aya-global").strip(),
            hf_key,
            hf_base,
            hf_tasks,
            False,
            _priority("huggingface", 0),
            cost_per_1k_tokens=_cost(
                os.getenv("HF_MODEL_COST_PER_1K_TOKENS"),
                "HF_MODEL_COST_PER_1K_TOKENS",
            ),
        ))
        vision_model = os.getenv(
            "HF_VISION_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"
        ).strip()
        if vision_model:
            specs.append(ModelSpec(
                "huggingface", vision_model, hf_key, hf_base, hf_tasks, True,
                _priority("huggingface", 1),
                cost_per_1k_tokens=_cost(
                    os.getenv("HF_VISION_MODEL_COST_PER_1K_TOKENS"),
                    "HF_VISION_MODEL_COST_PER_1K_TOKENS",
                ),
            ))

    maximum_cost = _cost(
        os.getenv("AI_MAX_COST_PER_1K_TOKENS"), "AI_MAX_COST_PER_1K_TOKENS"
    )
    if maximum_cost is not None:
        specs = [
            spec for spec in specs
            if spec.cost_per_1k_tokens is not None
            and spec.cost_per_1k_tokens <= maximum_cost
        ]
    return sorted(
        specs,
        key=lambda spec: (
            spec.priority,
            spec.cost_per_1k_tokens if spec.cost_per_1k_tokens is not None else math.inf,
            spec.provider,
            spec.model,
        ),
    )


def _media_parts(contents) -> list[tuple[str, bytes]]:
    media: list[tuple[str, bytes]] = []
    entries = contents if isinstance(contents, list) else [contents]
    for entry in entries:
        parts = getattr(entry, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None:
                data = inline.data
                if isinstance(data, str):
                    data = data.encode("utf-8")
                media.append((inline.mime_type, data))
    return media


def supports_input(spec: ModelSpec, contents) -> bool:
    media = _media_parts(contents)
    if not media:
        return True
    return spec.vision and all(
        mime_type in spec.image_types for mime_type, _ in media
    )


def models_for(task: str, contents) -> list[ModelSpec]:
    compatible = [
        spec for spec in configured_models()
        if (task in spec.tasks or "*" in spec.tasks)
        and supports_input(spec, contents)
        and not is_cooling_down(spec.key)
    ]
    task_ready = [
        spec for spec in compatible
        if not is_cooling_down(task_cooldown_key(spec, task))
    ]
    return task_ready or compatible


def task_cooldown_key(spec: ModelSpec, task: str) -> str:
    return f"{spec.key}:{task}"


def _openai_messages(contents, system: str) -> list[dict]:
    messages = [{"role": "system", "content": system}]
    entries = contents if isinstance(contents, list) else [contents]
    for entry in entries:
        if isinstance(entry, str):
            messages.append({"role": "user", "content": entry})
            continue
        role = "assistant" if getattr(entry, "role", "user") == "model" else "user"
        text_and_media = []
        for part in getattr(entry, "parts", None) or []:
            text = getattr(part, "text", None)
            if text:
                text_and_media.append({"type": "text", "text": text})
            inline = getattr(part, "inline_data", None)
            if inline is not None:
                payload = base64.b64encode(inline.data).decode("ascii")
                text_and_media.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{inline.mime_type};base64,{payload}",
                    },
                })
        if text_and_media:
            content = text_and_media[0]["text"] if (
                len(text_and_media) == 1 and text_and_media[0]["type"] == "text"
            ) else text_and_media
            messages.append({"role": role, "content": content})
    return messages


def _failure_from_response(
    status_code: int,
    body: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ProviderFailure:
    text = body.lower()
    quota = any(word in text for word in ("quota", "billing", "resource_exhausted"))
    model_name = f" for {provider} model {model}" if provider and model else ""
    if status_code == 429 or (status_code == 403 and quota):
        category = "quota_exhausted" if quota else "rate_limit"
        return ProviderFailure(category, "Provider quota or rate limit reached.",
                               retryable=True, status_code=status_code)
    if status_code == 401 or status_code == 403:
        return ProviderFailure("authentication", "Provider authentication failed.",
                               status_code=status_code)
    if status_code in (408, 425, 500, 502, 503, 504):
        return ProviderFailure("temporary_unavailable", "Provider is temporarily unavailable.",
                               retryable=True, status_code=status_code)
    return ProviderFailure(
        "invalid_request",
        f"Provider rejected the request{model_name} (HTTP {status_code}). "
        "Check that the configured model supports this request.",
                           status_code=status_code)


def _request_body(spec: ModelSpec, contents, system: str, config) -> dict:
    body = {
        "model": spec.model,
        "messages": _openai_messages(contents, system),
        "temperature": getattr(config, "temperature", 0.4),
        "max_tokens": getattr(config, "max_output_tokens", 512),
    }
    if getattr(config, "response_mime_type", None) == "application/json":
        body["response_format"] = {"type": "json_object"}
    return body


def generate(spec: ModelSpec, contents, system: str, config) -> tuple[str, dict]:
    url = f"{spec.base_url}/chat/completions"
    try:
        response = _get_http_client().post(
            url,
            headers={"Authorization": f"Bearer {spec.api_key}"},
            json=_request_body(spec, contents, system, config),
            timeout=_TIMEOUT_SECONDS,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ProviderFailure(
            "temporary_unavailable", "Provider request timed out or could not connect.",
            retryable=True,
        ) from exc
    if response.is_error:
        raise _failure_from_response(
            response.status_code,
            response.text,
            provider=spec.provider,
            model=spec.model,
        )
    try:
        payload = response.json()
        text = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ProviderFailure("invalid_response", "Provider returned an invalid response.") from exc
    if isinstance(text, list):
        text = "".join(
            item.get("text", "") for item in text if isinstance(item, dict)
        )
    usage = payload.get("usage") or {}
    return str(text or "").strip(), {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
    }


def generate_stream(
    spec: ModelSpec, contents, system: str, config
) -> Iterator[str]:
    url = f"{spec.base_url}/chat/completions"
    body = _request_body(spec, contents, system, config)
    body["stream"] = True
    try:
        with _get_http_client().stream(
            "POST",
            url,
            headers={"Authorization": f"Bearer {spec.api_key}"},
            json=body,
            timeout=_TIMEOUT_SECONDS,
        ) as response:
            if response.is_error:
                raise _failure_from_response(response.status_code, response.read().decode(
                    "utf-8", errors="replace"
                ), provider=spec.provider, model=spec.model)
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    payload = json.loads(data)
                    delta = payload["choices"][0].get("delta", {}).get("content")
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise ProviderFailure(
                        "invalid_response", "Provider returned an invalid stream."
                    ) from exc
                if isinstance(delta, str) and delta:
                    yield delta
    except ProviderFailure:
        raise
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise ProviderFailure(
            "temporary_unavailable", "Provider request timed out or could not connect.",
            retryable=True,
        ) from exc


def is_cooling_down(key: str) -> bool:
    with _health_lock:
        until = _cooldowns.get(key, 0)
        if until <= time.monotonic():
            _cooldowns.pop(key, None)
            return False
        return True


def record_health(key: str, *, healthy: bool, cooldown_seconds: float | None = None) -> None:
    with _health_lock:
        if healthy:
            _cooldowns.pop(key, None)
        else:
            duration = cooldown_seconds
            if duration is None:
                duration = max(1.0, float(os.getenv("AI_PROVIDER_COOLDOWN_SECONDS", "60")))
            _cooldowns[key] = time.monotonic() + duration


def reset_health() -> None:
    with _health_lock:
        _cooldowns.clear()


def provider_health() -> list[dict]:
    return [
        {
            "provider": spec.provider,
            "model": spec.model,
            "available": not is_cooling_down(spec.key),
        }
        for spec in configured_models()
    ]


def log_attempt(
    *,
    request_id: str,
    provider: str,
    model: str,
    task: str,
    status: str,
    fallback_attempt: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error_category: str | None = None,
) -> None:
    global _usage_schema_warning_logged
    if sb is None:
        return
    try:
        sb.table("ai_usage").insert({
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "request_type": task,
            "status": status,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "fallback_attempt": fallback_attempt,
            "error_category": error_category,
        }).execute()
    except Exception as exc:
        if getattr(exc, "code", None) == "PGRST205":
            if not _usage_schema_warning_logged:
                logger.warning(
                    "Supabase AI usage table is missing; apply "
                    "supabase/migrations/20261117_ai_usage.sql."
                )
                _usage_schema_warning_logged = True
        else:
            logger.exception("Could not record AI provider usage in Supabase")


def new_request_id() -> str:
    return str(uuid.uuid4())
