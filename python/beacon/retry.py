"""Deterministic retry classification.

>>> from beacon import retry
>>> decision = retry.classify(TimeoutError("read timed out"))
>>> decision.action, decision.reason
(<RetryAction.RETRY: 'retry'>, <RetryReason.TIMEOUT: 'timeout'>)

Classification uses the HTTP status code when the exception carries one
(``status_code``, ``status``, ``http_status`` or ``response.status_code``),
then the class names in the exception's MRO (any module — so ``openai``,
``anthropic``, ``httpx``, ``requests``, ``google.api_core`` and builtin
exceptions are all covered), else ``unknown_error`` (not retried).

Delays are exponential, capped, and jittered *deterministically*: the jitter
is derived from ``RetryPolicy.jitter_key`` and the attempt number, so the
same failure sequence always produces the same delays. Give each client or
request its own ``jitter_key`` to spread retries out.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar, Union

from . import _beacon_native as _native

__all__ = ["RetryAction", "RetryReason", "RetryDecision", "RetryPolicy", "classify", "backoff_delay", "call"]

T = TypeVar("T")


class RetryAction(str, enum.Enum):
    RETRY = "retry"
    FAIL = "fail"


class RetryReason(str, enum.Enum):
    RATE_LIMIT = "rate_limit"
    OVERLOADED = "overloaded"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    CONFLICT = "conflict"
    AUTH_ERROR = "auth_error"
    BAD_REQUEST = "bad_request"
    NOT_FOUND = "not_found"
    REQUEST_TOO_LARGE = "request_too_large"
    CLIENT_ERROR = "client_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True)
class RetryPolicy:
    """How many times to try and how long to wait.

    Attributes:
        max_attempts: Total attempts including the first (``>= 1``).
        base_delay_ms: Delay after the first failure.
        max_delay_ms: Cap for any delay, including server ``Retry-After``.
        jitter_percent: Up to this share of each delay is subtracted (0–100).
        jitter_key: Seed for the deterministic jitter.
    """

    max_attempts: int = 5
    base_delay_ms: int = 1000
    max_delay_ms: int = 60_000
    jitter_percent: int = 20
    jitter_key: str = ""

    def _args(self) -> tuple[int, int, int, int, str]:
        return (self.max_attempts, self.base_delay_ms, self.max_delay_ms, self.jitter_percent, self.jitter_key)


DEFAULT_POLICY = RetryPolicy()


@dataclass(frozen=True)
class RetryDecision:
    """What to do after a failed attempt.

    ``action`` is :attr:`RetryAction.RETRY` or :attr:`RetryAction.FAIL`;
    ``retryable`` says whether the error kind is retryable at all (it can be
    ``True`` with ``action == FAIL`` once ``max_attempts`` is reached).
    """

    action: RetryAction
    reason: RetryReason
    delay_seconds: float
    attempt: int
    retryable: bool

    @property
    def should_retry(self) -> bool:
        return self.action is RetryAction.RETRY


_RETRYABLE = {
    RetryReason.RATE_LIMIT,
    RetryReason.OVERLOADED,
    RetryReason.SERVER_ERROR,
    RetryReason.TIMEOUT,
    RetryReason.CONNECTION_ERROR,
    RetryReason.CONFLICT,
}


def _status_of(exc: BaseException) -> Optional[int]:
    for attr in ("status_code", "status", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _header(exc: BaseException, name: str) -> Optional[str]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except Exception:  # headers objects from unknown libraries
        return None
    return value if isinstance(value, str) else None


def classify(
    error: Union[BaseException, int],
    *,
    attempt: int = 1,
    policy: RetryPolicy = DEFAULT_POLICY,
) -> RetryDecision:
    """Decide whether to retry after ``attempt`` failed attempts (1-based).

    ``error`` is an exception or a bare HTTP status code.

    Retryable: rate limits (429), overload (503/529), server errors (5xx),
    timeouts (408 and timeout exceptions), connection errors, conflicts (409).
    Not retryable: auth (401/403), bad request (400/422), not found (404),
    request too large (413), other 4xx, and anything unrecognised.

    A numeric ``Retry-After`` / ``retry-after-ms`` response header is honoured
    (capped at ``max_delay_ms``); HTTP-date values are ignored because using
    them would require reading the clock.
    """
    if isinstance(error, bool) or not isinstance(error, (BaseException, int)):
        raise TypeError(f"error must be an exception or an int status code, got {type(error).__name__}")
    if isinstance(error, int):
        names: list[str] = []
        status: Optional[int] = error
        retry_after = retry_after_ms = None
    else:
        names = [cls.__name__ for cls in type(error).__mro__]
        status = _status_of(error)
        retry_after = _header(error, "retry-after")
        retry_after_ms = _header(error, "retry-after-ms")
    retry, reason, delay_ms, attempt_out = _native.retry_classify(
        names, status, retry_after, retry_after_ms, attempt, *policy._args()
    )
    reason_enum = RetryReason(reason)
    return RetryDecision(
        action=RetryAction.RETRY if retry else RetryAction.FAIL,
        reason=reason_enum,
        delay_seconds=delay_ms / 1000,
        attempt=attempt_out,
        retryable=reason_enum in _RETRYABLE,
    )


def backoff_delay(attempt: int, *, policy: RetryPolicy = DEFAULT_POLICY) -> float:
    """The backoff delay in seconds after ``attempt`` failures (no classification)."""
    return _native.retry_backoff_ms(attempt, *policy._args()) / 1000


def call(
    fn: Callable[..., T],
    /,
    *args: Any,
    policy: RetryPolicy = DEFAULT_POLICY,
    sleep: Callable[[float], Any] = time.sleep,
    on_retry: Optional[Callable[[BaseException, RetryDecision], Any]] = None,
    **kwargs: Any,
) -> T:
    """Call ``fn(*args, **kwargs)``, retrying according to :func:`classify`.

    The decisions and delays are deterministic; only the waiting happens in
    real time (inject ``sleep`` to make tests instant). The last exception is
    re-raised when the error is not retryable or attempts run out.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            decision = classify(exc, attempt=attempt, policy=policy)
            if not decision.should_retry:
                raise
            if on_retry is not None:
                on_retry(exc, decision)
            sleep(decision.delay_seconds)
