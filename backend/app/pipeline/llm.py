"""LLM provider for the judge node: Mistral primary, Groq fallback.

Raw httpx against the shared OpenAI-shaped chat-completions dialect — no SDKs
(tests inject a fake via set_provider(), mirroring services/embeddings.py).

Capabilities differ (verified against provider docs):
- Mistral supports strict schema output: response_format json_schema envelope.
- Groq (llama-3.3-70b-versatile) supports {"type": "json_object"} only.
Pydantic (DraftFinding, strict + extra=forbid) is the real gate either way.

Expected failures RETURN an LLMOutcome instead of raising, so per-call
provenance (which provider, which status, when) survives total failure and is
persisted in llm_calls.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import httpx

from app.config import settings

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUEST_TIMEOUT = 60.0

# llm_calls.status values
CALL_SUCCESS = "SUCCESS"
CALL_HTTP_ERROR = "HTTP_ERROR"
CALL_NETWORK_ERROR = "NETWORK_ERROR"
CALL_SKIPPED_NO_KEY = "SKIPPED_NO_KEY"


@dataclass
class LLMCall:
    """One HTTP attempt against one provider."""

    provider: str
    requested_model: str
    status: str
    request_messages: list[dict]
    response_format: dict
    temperature: float
    reported_model: str | None = None
    http_status: int | None = None
    error: str | None = None
    raw_response: str | None = None
    started_at: str = ""
    finished_at: str = ""


@dataclass
class LLMOutcome:
    content: str | None  # None = all providers failed
    calls: list[LLMCall] = field(default_factory=list)
    error: str | None = None

    @property
    def final_call(self) -> LLMCall | None:
        for call in reversed(self.calls):
            if call.status == CALL_SUCCESS:
                return call
        return None


class LLMProvider(Protocol):
    def complete_json(self, messages: list[dict], *, json_schema: dict | None = None) -> LLMOutcome: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mistral_response_format(json_schema: dict | None) -> dict:
    """Mistral's json_schema envelope is part of the API contract."""
    if json_schema is None:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": "draft_finding", "strict": True, "schema": json_schema},
    }


def groq_response_format(json_schema: dict | None) -> dict:
    # llama-3.3-70b-versatile: JSON Object Mode only; Pydantic validates.
    return {"type": "json_object"}


class HttpJsonLLM:
    """Mistral La Plateforme primary; Groq fallback on missing key/429/5xx/network."""

    def complete_json(self, messages: list[dict], *, json_schema: dict | None = None) -> LLMOutcome:
        calls: list[LLMCall] = []
        providers = [
            (
                "mistral",
                MISTRAL_URL,
                settings.mistral_api_key,
                settings.judge_model,
                mistral_response_format(json_schema),
            ),
            (
                "groq",
                GROQ_URL,
                settings.groq_api_key,
                settings.judge_fallback_model,
                groq_response_format(json_schema),
            ),
        ]
        for provider, url, api_key, model, response_format in providers:
            call = LLMCall(
                provider=provider,
                requested_model=model,
                status=CALL_SKIPPED_NO_KEY,
                request_messages=messages,
                response_format=response_format,
                temperature=settings.judge_temperature,
                started_at=_now(),
            )
            if not api_key:
                call.error = "clé API absente"
                call.finished_at = _now()
                calls.append(call)
                continue
            try:
                resp = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": settings.judge_temperature,
                        "response_format": response_format,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
            except httpx.HTTPError as exc:
                call.status = CALL_NETWORK_ERROR
                call.error = f"{type(exc).__name__}: {exc}"
                call.finished_at = _now()
                calls.append(call)
                continue
            call.http_status = resp.status_code
            call.finished_at = _now()
            if resp.status_code != 200:
                call.status = CALL_HTTP_ERROR
                call.error = resp.text[:2000]
                calls.append(call)
                # 4xx other than 429 will fail identically on retry elsewhere,
                # but the fallback provider may still succeed — always try it.
                continue
            data = resp.json()
            call.status = CALL_SUCCESS
            call.reported_model = data.get("model")
            call.raw_response = data["choices"][0]["message"]["content"]
            calls.append(call)
            return LLMOutcome(content=call.raw_response, calls=calls)
        return LLMOutcome(
            content=None,
            calls=calls,
            error="tous les fournisseurs LLM ont échoué : "
            + " ; ".join(f"{c.provider}: {c.status}" for c in calls),
        )


_provider: LLMProvider | None = None


def set_provider(provider: LLMProvider | None) -> None:
    """Test hook — mirrors services/embeddings.py."""
    global _provider
    _provider = provider


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = HttpJsonLLM()
    return _provider


def complete_json(messages: list[dict], *, json_schema: dict | None = None) -> LLMOutcome:
    return get_provider().complete_json(messages, json_schema=json_schema)
