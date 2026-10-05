"""Single choke point for every Groq call made by the API.

Responsibilities:
1. Key pool: one httpx client per org key (GROQ_API_KEY, GROQ_API_KEY_FALLBACK), same model on both.
2. Local rate limiting per key: sliding 60s window for requests + estimated tokens
   (input estimate + reserved max_tokens), refined by the x-ratelimit-* response headers.
3. Cooldowns: a 429 puts that key to sleep for Retry-After; the call retries once on the other key.
4. Error classification so callers can react correctly:
   - LLMUnavailable: rate limited / outage / no usable key (carries retry_after seconds)
   - LLMTruncated:   output cut off, invalid JSON, or request too large -> caller should shrink the batch
   - LLMBadResponse: anything else unusable (bad model id, 4xx, malformed body)
5. Structured logging of every attempt (key label only, never the key itself).
"""
import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("groq_gateway")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
WINDOW_SECONDS = 60.0


class GroqError(Exception):
    """Base class for gateway failures."""


class LLMUnavailable(GroqError):
    """Rate limited, offline, or no usable key. Retry after `retry_after` seconds."""

    def __init__(self, retry_after: float, reason: str = ""):
        super().__init__(reason or f"Groq unavailable; retry in {retry_after:.0f}s")
        self.retry_after = max(1.0, float(retry_after))
        self.reason = reason


class LLMTruncated(GroqError):
    """Output was cut off / not valid JSON / request too large. Caller should shrink the batch."""


class LLMBadResponse(GroqError):
    """Unusable response that retrying the same request will not fix."""


@dataclass
class GroqResult:
    data: Dict[str, Any]
    total_tokens: int
    key_label: str
    latency: float


@dataclass
class KeyState:
    label: str
    api_key: str
    client: httpx.AsyncClient
    req_log: Deque[List[float]] = field(default_factory=deque)   # [timestamp]
    tok_log: Deque[List[float]] = field(default_factory=deque)   # [timestamp, tokens]
    cooldown_until: float = 0.0
    disabled: bool = False
    hdr_remaining_tokens: Optional[float] = None
    hdr_reset_at: float = 0.0
    org_id: Optional[str] = None


_DURATION_RE = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?")


def parse_duration(value: Optional[str]) -> Optional[float]:
    """Parses Groq reset values like '7.66s', '2m59.56s', '120' or '350ms' into seconds."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    m = _DURATION_RE.fullmatch(value)
    if not m or not any(m.groups()):
        return None
    hours, minutes, seconds, millis = (float(g) if g else 0.0 for g in m.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def estimate_tokens(messages: List[Dict[str, str]]) -> int:
    """Deliberately pessimistic (JSON-heavy text is ~3 chars/token)."""
    chars = sum(len(m.get("content") or "") for m in messages)
    return int(chars / 3.0) + 40


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class GroqGateway:
    def __init__(
        self,
        keys: List[Tuple[str, str]],
        *,
        model: str = "openai/gpt-oss-20b",
        rpm: int = 25,
        tpm: int = 6500,
        timeout: float = 10.0,
        reasoning_effort: Optional[str] = "low",
        include_reasoning: bool = False,
        max_inflight: int = 2,
        max_attempts: int = 2,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ):
        self.model = model
        self.rpm = rpm
        self.tpm = tpm
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort
        self.include_reasoning = include_reasoning
        self.max_attempts = max(1, max_attempts)
        self._clock = clock
        self._sleep = sleep
        self._send_reasoning_params = True
        self._warned_shared_org = False
        self._lock = asyncio.Lock()
        self._inflight = asyncio.Semaphore(max_inflight)
        self.keys: List[KeyState] = []
        for label, api_key in keys:
            client = httpx.AsyncClient(
                timeout=timeout,
                transport=transport,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            self.keys.append(KeyState(label=label, api_key=api_key, client=client))

    # ------------------------------------------------------------------ public

    @property
    def has_keys(self) -> bool:
        return any(not k.disabled for k in self.keys)

    async def aclose(self) -> None:
        for k in self.keys:
            if not k.client.is_closed:
                await k.client.aclose()

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int,
        purpose: str = "",
        max_wait: float = 10.0,
    ) -> GroqResult:
        """Runs one JSON-mode chat completion through the key pool and limiter."""
        est = estimate_tokens(messages) + max_tokens
        attempts = 0
        while True:
            key, tok_entry, wait = await self._acquire(est, max_wait)
            if wait > 0:
                await self._sleep(wait)

            started = self._clock()
            try:
                async with self._inflight:
                    resp = await key.client.post(GROQ_URL, json=self._body(messages, max_tokens))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                tok_entry[1] = 0
                key.cooldown_until = max(key.cooldown_until, self._clock() + 2.0)
                attempts += 1
                logger.warning("groq purpose=%s key=%s transport_error=%s attempt=%d", purpose, key.label, type(exc).__name__, attempts)
                if attempts >= self.max_attempts:
                    raise LLMUnavailable(5.0, f"transport error: {type(exc).__name__}")
                continue

            latency = self._clock() - started
            self._read_headers(key, resp.headers)
            status = resp.status_code

            if status == 200:
                return self._handle_ok(resp, key, tok_entry, est, latency, purpose)

            body_text = (resp.text or "")[:300]
            logger.warning(
                "groq purpose=%s key=%s status=%d latency=%.2fs remaining_tokens=%s body=%s",
                purpose, key.label, status, latency, key.hdr_remaining_tokens, body_text.replace("\n", " "),
            )
            tok_entry[1] = 0

            if status == 429:
                retry_after = parse_duration(resp.headers.get("retry-after"))
                if retry_after is None:
                    retry_after = max(key.hdr_reset_at - self._clock(), 0.0) or 15.0
                key.cooldown_until = self._clock() + retry_after
                self._share_cooldown_within_org(key, body_text)
                attempts += 1
                if attempts >= self.max_attempts:
                    raise LLMUnavailable(self._soonest_available(), "rate limited on all attempts")
                continue

            if status == 400:
                lowered = body_text.lower()
                if self._send_reasoning_params and "reasoning" in lowered:
                    # Model rejects reasoning params; drop them for good and retry immediately.
                    self._send_reasoning_params = False
                    logger.error("groq rejected reasoning params; disabling them. body=%s", body_text)
                    continue
                if "json_validate_failed" in lowered or "max completion tokens" in lowered or "max_tokens" in lowered:
                    raise LLMTruncated(f"400 {body_text}")
                raise LLMBadResponse(f"400 {body_text}")

            if status == 413:
                raise LLMTruncated("413 request too large")

            if status in (401, 403):
                key.disabled = True
                logger.error("groq key %s disabled after HTTP %d", key.label, status)
                attempts += 1
                if not self.has_keys:
                    raise LLMUnavailable(3600.0, f"all Groq keys rejected (HTTP {status})")
                if attempts >= self.max_attempts:
                    raise LLMUnavailable(self._soonest_available(), f"auth failure HTTP {status}")
                continue

            if status >= 500:
                key.cooldown_until = max(key.cooldown_until, self._clock() + 2.0)
                attempts += 1
                if attempts >= self.max_attempts:
                    raise LLMUnavailable(5.0, f"upstream HTTP {status}")
                continue

            raise LLMBadResponse(f"HTTP {status} {body_text}")

    def snapshot(self) -> Dict[str, Any]:
        now = self._clock()
        out = {}
        for k in self.keys:
            self._prune(k, now)
            out[k.label] = {
                "disabled": k.disabled,
                "cooldown_s": max(0.0, k.cooldown_until - now),
                "requests_in_window": len(k.req_log),
                "tokens_in_window": sum(e[1] for e in k.tok_log),
            }
        return out

    # ---------------------------------------------------------------- internals

    def _body(self, messages: List[Dict[str, str]], max_tokens: int) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "seed": 42,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self._send_reasoning_params:
            if self.reasoning_effort:
                body["reasoning_effort"] = self.reasoning_effort
            if not self.include_reasoning:
                body["include_reasoning"] = False
        return body

    def _handle_ok(self, resp: httpx.Response, key: KeyState, tok_entry: List[float], est: int, latency: float, purpose: str) -> GroqResult:
        try:
            payload = resp.json()
            choice = payload["choices"][0]
            content = (choice.get("message") or {}).get("content") or ""
            finish = choice.get("finish_reason")
            usage = payload.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            tok_entry[1] = 0
            raise LLMBadResponse(f"malformed 200 body: {exc}")

        total = int(usage.get("total_tokens") or est)
        tok_entry[1] = total
        logger.info(
            "groq purpose=%s key=%s status=200 latency=%.2fs tokens=%d finish=%s remaining_tokens=%s",
            purpose, key.label, latency, total, finish, key.hdr_remaining_tokens,
        )
        if finish == "length":
            raise LLMTruncated("finish_reason=length")
        try:
            data = json.loads(content)
        except ValueError:
            raise LLMTruncated("response content is not valid JSON")
        if not isinstance(data, dict):
            raise LLMBadResponse("JSON response is not an object")
        return GroqResult(data=data, total_tokens=total, key_label=key.label, latency=latency)

    def _share_cooldown_within_org(self, key: KeyState, body_text: str) -> None:
        """Rate limits are per ORG. If the 429 names the org, every key in that org is limited too, so
        cool them all down instead of burning a request on a sibling key (and warn about shared orgs)."""
        m = re.search(r"organization `(org_[A-Za-z0-9]+)`", body_text)
        if not m:
            return
        key.org_id = m.group(1)
        for other in self.keys:
            if other is not key and other.org_id == key.org_id:
                other.cooldown_until = max(other.cooldown_until, key.cooldown_until)
                if not self._warned_shared_org:
                    self._warned_shared_org = True
                    logger.warning(
                        "Groq keys %s and %s belong to the SAME org (%s): they share one rate-limit budget. "
                        "Use a key from a different Groq account/org for extra capacity.",
                        key.label, other.label, key.org_id,
                    )

    def _read_headers(self, key: KeyState, headers: httpx.Headers) -> None:
        remaining = headers.get("x-ratelimit-remaining-tokens")
        reset = parse_duration(headers.get("x-ratelimit-reset-tokens"))
        if remaining is not None:
            try:
                key.hdr_remaining_tokens = float(remaining)
            except ValueError:
                key.hdr_remaining_tokens = None
        if reset is not None:
            key.hdr_reset_at = self._clock() + reset

    def _prune(self, key: KeyState, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        while key.req_log and key.req_log[0][0] <= cutoff:
            key.req_log.popleft()
        while key.tok_log and key.tok_log[0][0] <= cutoff:
            key.tok_log.popleft()

    def _ready_at(self, key: KeyState, now: float, est: int) -> float:
        """Earliest time this key can take a request of `est` tokens."""
        self._prune(key, now)
        t = max(now, key.cooldown_until)

        if len(key.req_log) >= self.rpm:
            t = max(t, key.req_log[len(key.req_log) - self.rpm][0] + WINDOW_SECONDS)

        need = min(est, self.tpm)  # a request bigger than the whole budget must still be able to run
        budget = self.tpm - need
        total = sum(e[1] for e in key.tok_log)
        if total > budget:
            running = total
            for ts, tokens in key.tok_log:
                running -= tokens
                if running <= budget:
                    t = max(t, ts + WINDOW_SECONDS)
                    break

        if key.hdr_remaining_tokens is not None and now < key.hdr_reset_at and est > key.hdr_remaining_tokens:
            t = max(t, key.hdr_reset_at)
        return t

    async def _acquire(self, est: int, max_wait: float) -> Tuple[KeyState, List[float], float]:
        """Picks the key that is ready soonest (ties -> most spare budget) and reserves capacity on it."""
        async with self._lock:
            now = self._clock()
            active = [k for k in self.keys if not k.disabled]
            if not active:
                raise LLMUnavailable(3600.0, "no usable Groq API key configured")

            best: Optional[Tuple[float, float, KeyState]] = None
            for k in active:
                ready = self._ready_at(k, now, est)
                spare = self.tpm - sum(e[1] for e in k.tok_log)
                score = (ready, -spare)
                if best is None or score < (best[0], best[1]):
                    best = (ready, -spare, k)
            ready, _, key = best  # type: ignore[misc]
            wait = max(0.0, ready - now)
            if wait > max_wait:
                raise LLMUnavailable(wait, f"all keys busy/cooling for {wait:.0f}s")

            key.req_log.append([ready])
            tok_entry: List[float] = [ready, float(est)]
            key.tok_log.append(tok_entry)
            return key, tok_entry, wait

    def _soonest_available(self) -> float:
        now = self._clock()
        waits = [max(0.0, k.cooldown_until - now) for k in self.keys if not k.disabled]
        return max(1.0, min(waits)) if waits else 3600.0


# ---------------------------------------------------------------------- singleton

_gateway: Optional[GroqGateway] = None


def build_gateway_from_env() -> GroqGateway:
    keys: List[Tuple[str, str]] = []
    seen = set()
    for label, env_name in (("k1", "GROQ_API_KEY"), ("k2", "GROQ_API_KEY_FALLBACK")):
        value = (os.getenv(env_name) or "").strip()
        if value and value not in seen:
            seen.add(value)
            keys.append((label, value))
    effort = (os.getenv("GROQ_REASONING_EFFORT", "low") or "").strip().lower() or None
    return GroqGateway(
        keys,
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        rpm=int(_env_float("GROQ_RPM", 25)),
        tpm=int(_env_float("GROQ_TPM", 6500)),
        timeout=_env_float("GROQ_TIMEOUT", 10.0),
        reasoning_effort=effort,
        include_reasoning=_env_bool("GROQ_INCLUDE_REASONING", False),
        max_inflight=int(_env_float("GROQ_MAX_INFLIGHT", 2)),
    )


def get_gateway() -> GroqGateway:
    global _gateway
    if _gateway is None:
        _gateway = build_gateway_from_env()
        logger.info(
            "Groq gateway ready: model=%s keys=%d rpm=%d tpm=%d timeout=%.0fs",
            _gateway.model, len(_gateway.keys), _gateway.rpm, _gateway.tpm, _gateway.timeout,
        )
    return _gateway


async def close_gateway() -> None:
    global _gateway
    if _gateway is not None:
        await _gateway.aclose()
        _gateway = None
