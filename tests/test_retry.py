from __future__ import annotations

from typing import Any, Optional

import pytest

from beacon import RetryAction, RetryDecision, RetryPolicy, RetryReason, retry
from beacon.snapshots import assert_snapshot

NO_JITTER = RetryPolicy(max_attempts=5, base_delay_ms=1000, max_delay_ms=30_000, jitter_percent=0)


class _Response:
    def __init__(self, status: int, headers: Optional[dict[str, str]] = None) -> None:
        self.status_code = status
        self.headers = headers or {}


def make_error(name: str, *, status: Optional[int] = None, headers: Optional[dict[str, str]] = None, base: type = Exception) -> BaseException:
    """An exception class named like the SDK one (module names do not matter)."""
    cls = type(name, (base,), {})
    exc = cls("boom")
    if status is not None:
        exc.status_code = status  # type: ignore[attr-defined]
        exc.response = _Response(status, headers)  # type: ignore[attr-defined]
    return exc


@pytest.mark.parametrize(
    "exc,reason,action",
    [
        (make_error("RateLimitError", status=429), RetryReason.RATE_LIMIT, RetryAction.RETRY),
        (make_error("InternalServerError", status=500), RetryReason.SERVER_ERROR, RetryAction.RETRY),
        (make_error("APIStatusError", status=502), RetryReason.SERVER_ERROR, RetryAction.RETRY),
        (make_error("APIStatusError", status=503), RetryReason.OVERLOADED, RetryAction.RETRY),
        (make_error("OverloadedError", status=529), RetryReason.OVERLOADED, RetryAction.RETRY),
        (make_error("APITimeoutError"), RetryReason.TIMEOUT, RetryAction.RETRY),
        (make_error("APIConnectionError"), RetryReason.CONNECTION_ERROR, RetryAction.RETRY),
        (make_error("ConflictError", status=409), RetryReason.CONFLICT, RetryAction.RETRY),
        (make_error("AuthenticationError", status=401), RetryReason.AUTH_ERROR, RetryAction.FAIL),
        (make_error("PermissionDeniedError", status=403), RetryReason.AUTH_ERROR, RetryAction.FAIL),
        (make_error("BadRequestError", status=400), RetryReason.BAD_REQUEST, RetryAction.FAIL),
        (make_error("UnprocessableEntityError", status=422), RetryReason.BAD_REQUEST, RetryAction.FAIL),
        (make_error("NotFoundError", status=404), RetryReason.NOT_FOUND, RetryAction.FAIL),
        (make_error("APIStatusError", status=413), RetryReason.REQUEST_TOO_LARGE, RetryAction.FAIL),
        (make_error("APIStatusError", status=418), RetryReason.CLIENT_ERROR, RetryAction.FAIL),
        (make_error("ReadTimeout"), RetryReason.TIMEOUT, RetryAction.RETRY),
        (make_error("ConnectError"), RetryReason.CONNECTION_ERROR, RetryAction.RETRY),
        (make_error("ResourceExhausted"), RetryReason.RATE_LIMIT, RetryAction.RETRY),
        (make_error("ServiceUnavailable"), RetryReason.OVERLOADED, RetryAction.RETRY),
        (make_error("DeadlineExceeded"), RetryReason.TIMEOUT, RetryAction.RETRY),
        (TimeoutError("t"), RetryReason.TIMEOUT, RetryAction.RETRY),
        (ConnectionResetError("r"), RetryReason.CONNECTION_ERROR, RetryAction.RETRY),
        (BrokenPipeError("p"), RetryReason.CONNECTION_ERROR, RetryAction.RETRY),
        (ValueError("v"), RetryReason.UNKNOWN_ERROR, RetryAction.FAIL),
        (KeyError("k"), RetryReason.UNKNOWN_ERROR, RetryAction.FAIL),
        (OSError("o"), RetryReason.UNKNOWN_ERROR, RetryAction.FAIL),
    ],
)
def test_classification(exc: BaseException, reason: RetryReason, action: RetryAction) -> None:
    d = retry.classify(exc, policy=NO_JITTER)
    assert (d.reason, d.action) == (reason, action)
    assert d.retryable == (action is RetryAction.RETRY)


def test_subclasses_resolve_via_mro() -> None:
    Base = type("APITimeoutError", (Exception,), {})
    Custom = type("MyCompanyTimeout", (Base,), {})
    assert retry.classify(Custom("x")).reason is RetryReason.TIMEOUT


def test_status_code_beats_class_name() -> None:
    exc = make_error("AuthenticationError", status=429)
    assert retry.classify(exc).reason is RetryReason.RATE_LIMIT


def test_status_from_response_only() -> None:
    exc = Exception("x")
    exc.response = _Response(503)  # type: ignore[attr-defined]
    assert retry.classify(exc).reason is RetryReason.OVERLOADED


def test_bare_status_codes() -> None:
    assert retry.classify(429).reason is RetryReason.RATE_LIMIT
    assert retry.classify(200).reason is RetryReason.UNKNOWN_ERROR
    with pytest.raises(TypeError):
        retry.classify("429")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        retry.classify(True)


def test_exponential_backoff_without_jitter() -> None:
    delays = [retry.classify(429, attempt=a, policy=NO_JITTER).delay_seconds for a in range(1, 5)]
    assert delays == [1.0, 2.0, 4.0, 8.0]
    assert [retry.backoff_delay(a, policy=NO_JITTER) for a in (5, 6, 99)] == [16.0, 30.0, 30.0]


def test_max_attempts() -> None:
    d = retry.classify(429, attempt=5, policy=NO_JITTER)
    assert d.action is RetryAction.FAIL and d.retryable and d.delay_seconds == 0.0


def test_deterministic_jitter() -> None:
    policy = RetryPolicy(jitter_percent=50, jitter_key="client-a")
    a = [retry.classify(429, attempt=n, policy=policy).delay_seconds for n in range(1, 5)]
    b = [retry.classify(429, attempt=n, policy=policy).delay_seconds for n in range(1, 5)]
    assert a == b
    for n, delay in enumerate(a, start=1):
        full = min(60.0, 2 ** (n - 1))
        assert full / 2 <= delay <= full
    other = [retry.classify(429, attempt=n, policy=RetryPolicy(jitter_percent=50, jitter_key="client-b")).delay_seconds for n in range(1, 5)]
    assert other != a


def test_retry_after_headers() -> None:
    exc = make_error("RateLimitError", status=429, headers={"retry-after": "7"})
    assert retry.classify(exc, policy=NO_JITTER).delay_seconds == 7.0
    exc = make_error("RateLimitError", status=429, headers={"retry-after-ms": "1500", "retry-after": "7"})
    assert retry.classify(exc, policy=NO_JITTER).delay_seconds == 1.5
    exc = make_error("RateLimitError", status=429, headers={"retry-after": "3600"})
    assert retry.classify(exc, policy=NO_JITTER).delay_seconds == 30.0  # capped
    exc = make_error("RateLimitError", status=429, headers={"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert retry.classify(exc, policy=NO_JITTER).delay_seconds == 1.0  # dates ignored


def test_policy_validation() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        retry.classify(429, policy=RetryPolicy(max_attempts=0))
    with pytest.raises(ValueError, match="jitter_percent"):
        retry.classify(429, policy=RetryPolicy(jitter_percent=101))
    with pytest.raises(ValueError, match="must not exceed"):
        retry.classify(429, policy=RetryPolicy(base_delay_ms=10, max_delay_ms=5))
    with pytest.raises(ValueError, match="attempt"):
        retry.classify(429, attempt=0)


def test_decision_is_typed() -> None:
    d = retry.classify(429, policy=NO_JITTER)
    assert isinstance(d, RetryDecision)
    assert d.action == "retry" and d.reason == "rate_limit"  # str enums compare to strings
    assert d.should_retry


def test_call_retries_then_succeeds() -> None:
    attempts: list[int] = []
    sleeps: list[float] = []

    def flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise make_error("RateLimitError", status=429)
        return "ok"

    seen: list[Any] = []
    assert retry.call(flaky, policy=NO_JITTER, sleep=sleeps.append, on_retry=lambda e, d: seen.append(d.reason)) == "ok"
    assert sleeps == [1.0, 2.0]
    assert seen == [RetryReason.RATE_LIMIT, RetryReason.RATE_LIMIT]


def test_call_does_not_retry_fatal_errors() -> None:
    sleeps: list[float] = []

    def broken() -> None:
        raise make_error("AuthenticationError", status=401)

    with pytest.raises(Exception, match="boom"):
        retry.call(broken, sleep=sleeps.append)
    assert sleeps == []


def test_call_gives_up_after_max_attempts() -> None:
    sleeps: list[float] = []

    def always() -> None:
        raise TimeoutError("slow")

    with pytest.raises(TimeoutError):
        retry.call(always, policy=RetryPolicy(max_attempts=3, jitter_percent=0), sleep=sleeps.append)
    assert sleeps == [1.0, 2.0]


def test_snapshot_decision_table() -> None:
    policy = RetryPolicy(jitter_percent=25, jitter_key="snapshot")
    table = {}
    for status in (400, 401, 403, 404, 408, 409, 413, 418, 422, 429, 500, 502, 503, 504, 529):
        d = retry.classify(status, attempt=2, policy=policy)
        table[str(status)] = {"action": d.action, "reason": d.reason, "delay_seconds": d.delay_seconds}
    assert_snapshot("retry/status_table", table)


def test_snapshot_backoff_schedule() -> None:
    policies = {
        "default": RetryPolicy(),
        "no_jitter": NO_JITTER,
        "keyed": RetryPolicy(jitter_percent=50, jitter_key="tenant-42"),
    }
    schedule = {name: [retry.backoff_delay(n, policy=p) for n in range(1, 9)] for name, p in policies.items()}
    assert_snapshot("retry/backoff_schedule", schedule)
