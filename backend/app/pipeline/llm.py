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

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

import httpx

# Corporate proxies intercept TLS with a root CA that lives in the OS store
# but not in certifi's bundle; truststore makes Python use the OS store.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # optional — plain environments work without it
    pass

from app.config import settings
from app.pipeline.state import AbstainReason

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUEST_TIMEOUT = 60.0
MAX_BACKOFF_SECONDS = 30.0  # cap on Retry-After / exponential delay

# llm_calls.status values
CALL_SUCCESS = "SUCCESS"
CALL_HTTP_ERROR = "HTTP_ERROR"
CALL_NETWORK_ERROR = "NETWORK_ERROR"
CALL_BAD_RESPONSE = "BAD_RESPONSE"  # HTTP 200 but unparseable body (proxy pages…)
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
    def complete_json(
        self,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        schema_name: str = "draft_finding",
        on_call_finished: Callable[[], None] | None = None,
    ) -> LLMOutcome: ...


def classify_failure(calls: list[LLMCall]) -> str:
    """Deterministic failure cause from a call trail (all providers failed).

    Exhausted 429s are throttling (infrastructure), not a generic provider
    failure — M6 must separate them at the finding level. rate_limited requires
    that throttling was the DECISIVE cause: a 429 somewhere in the trail
    followed by an unrelated terminal failure (5xx/4xx, network, malformed 200)
    is llm_error. Providers merely skipped for a missing key don't count as a
    competing failure. Single authority for every consumer (pipeline, chat) —
    see state.INFRASTRUCTURE_ABSTAIN_REASONS.
    """
    had_429 = any(c.http_status == 429 for c in calls)
    other_failure = any(
        c.status in (CALL_HTTP_ERROR, CALL_NETWORK_ERROR, CALL_BAD_RESPONSE)
        and c.http_status != 429
        for c in calls
    )
    return (
        AbstainReason.RATE_LIMITED.value
        if had_429 and not other_failure
        else AbstainReason.LLM_ERROR.value
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backoff_delay(resp: httpx.Response, backoff_round: int) -> float:
    """Retry-After when present, else exponential; always in [0, cap].

    RFC 9110 §10.2.3: the header is a non-negative integer of seconds OR an
    HTTP-date. Negative/garbage values must never reach time.sleep() (a
    negative sleep raises and would escape the LLMOutcome abstraction).
    """
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), MAX_BACKOFF_SECONDS)
        except ValueError:
            try:  # HTTP-date form
                from email.utils import parsedate_to_datetime

                delta = (
                    parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)
                ).total_seconds()
                return min(max(delta, 0.0), MAX_BACKOFF_SECONDS)
            except (ValueError, TypeError):
                pass  # unparseable header: fall through to exponential
    return min(settings.judge_429_base_delay * (2 ** backoff_round), MAX_BACKOFF_SECONDS)


def mistral_response_format(json_schema: dict | None, schema_name: str = "draft_finding") -> dict:
    """Mistral's json_schema envelope is part of the API contract."""
    if json_schema is None:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
    }


def groq_response_format(json_schema: dict | None) -> dict:
    # llama-3.3-70b-versatile: JSON Object Mode only; Pydantic validates.
    return {"type": "json_object"}


class HttpJsonLLM:
    """Mistral La Plateforme primary; Groq fallback on missing key/429/5xx/network."""

    def complete_json(
        self,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        schema_name: str = "draft_finding",
        on_call_finished: Callable[[], None] | None = None,
    ) -> LLMOutcome:
        """on_call_finished (optional) is invoked after EVERY provider call is
        recorded — success, failure or skip — and before any 429 backoff
        sleep. It exists for long-running callers that must renew a lease
        between calls (M7a planner heartbeat): the whole provider/fallback/
        retry loop is encapsulated here, so callers have no other observation
        point. Callback exceptions are the callback's problem — it must catch
        internally (the planner marks its lease lost instead of raising)."""
        calls: list[LLMCall] = []

        def _notify() -> None:
            if on_call_finished is not None:
                on_call_finished()

        providers = [
            (
                "mistral",
                MISTRAL_URL,
                settings.mistral_api_key,
                settings.judge_model,
                mistral_response_format(json_schema, schema_name),
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
            # Rate-limit handling (spec §12: batch runs must be throttled):
            # a 429 is retried on the SAME provider with exponential backoff
            # (honouring Retry-After), each retry logged as its own call —
            # falling straight through to the fallback would pollute M6
            # metrics with llm_error abstentions that are really throttling.
            for backoff_round in range(settings.judge_429_retries + 1):
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
                    _notify()
                    break  # no key: retrying is pointless, go to fallback
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
                    _notify()
                    break  # network error: try the fallback provider
                call.http_status = resp.status_code
                call.finished_at = _now()
                if resp.status_code != 200:
                    call.status = CALL_HTTP_ERROR
                    call.error = resp.text[:2000]
                    call.raw_response = resp.text[:2000]  # error body is provenance too
                    calls.append(call)
                    _notify()  # before the backoff sleep — lease renewal window
                    if resp.status_code == 429 and backoff_round < settings.judge_429_retries:
                        time.sleep(_backoff_delay(resp, backoff_round))
                        continue  # retry the same provider
                    # other 4xx/5xx (or 429 budget exhausted): try the fallback
                    break
                # HTTP 200 does not guarantee a well-formed body (intercepting
                # proxies return HTML pages with 200): parsing failures must
                # stay inside the failure-capable abstraction.
                try:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if not isinstance(content, str):
                        raise TypeError(f"content is {type(content).__name__}")
                except Exception as exc:
                    call.status = CALL_BAD_RESPONSE
                    call.error = f"réponse 200 malformée — {type(exc).__name__}: {exc}"
                    call.raw_response = resp.text[:2000]
                    calls.append(call)
                    _notify()
                    break  # the fallback provider may still succeed
                call.status = CALL_SUCCESS
                call.reported_model = data.get("model")
                call.raw_response = content
                calls.append(call)
                _notify()
                return LLMOutcome(content=content, calls=calls)
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


def complete_json(
    messages: list[dict],
    *,
    json_schema: dict | None = None,
    schema_name: str = "draft_finding",
    on_call_finished: Callable[[], None] | None = None,
) -> LLMOutcome:
    # The kwarg is forwarded only when set: existing fakes/providers that
    # predate it keep working unchanged for every caller that doesn't use it.
    if on_call_finished is None:
        return get_provider().complete_json(
            messages, json_schema=json_schema, schema_name=schema_name
        )
    return get_provider().complete_json(
        messages,
        json_schema=json_schema,
        schema_name=schema_name,
        on_call_finished=on_call_finished,
    )
