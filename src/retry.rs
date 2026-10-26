//! Deterministic retry classification and backoff.
//!
//! Classification looks at, in this fixed order:
//!
//! 1. the HTTP status code, if the error carries one;
//! 2. the class names in the exception's MRO, most-derived first, matched
//!    against a fixed table (module names are ignored, so `openai`,
//!    `anthropic`, `httpx`, `requests` and builtin exceptions are all handled);
//! 3. otherwise `unknown_error`, which is not retried.
//!
//! Delays are integer milliseconds. Jitter is derived from
//! `blake3(jitter_key ‖ attempt)`, never from a random number generator.

use crate::error::BlockError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reason {
    RateLimit,
    Overloaded,
    ServerError,
    Timeout,
    ConnectionError,
    Conflict,
    AuthError,
    BadRequest,
    NotFound,
    RequestTooLarge,
    ClientError,
    UnknownError,
}

impl Reason {
    pub fn as_str(self) -> &'static str {
        match self {
            Reason::RateLimit => "rate_limit",
            Reason::Overloaded => "overloaded",
            Reason::ServerError => "server_error",
            Reason::Timeout => "timeout",
            Reason::ConnectionError => "connection_error",
            Reason::Conflict => "conflict",
            Reason::AuthError => "auth_error",
            Reason::BadRequest => "bad_request",
            Reason::NotFound => "not_found",
            Reason::RequestTooLarge => "request_too_large",
            Reason::ClientError => "client_error",
            Reason::UnknownError => "unknown_error",
        }
    }

    pub fn retryable(self) -> bool {
        matches!(
            self,
            Reason::RateLimit
                | Reason::Overloaded
                | Reason::ServerError
                | Reason::Timeout
                | Reason::ConnectionError
                | Reason::Conflict
        )
    }
}

/// Maps an HTTP status code to a reason. `None` for non-error codes.
pub fn reason_for_status(status: u16) -> Option<Reason> {
    Some(match status {
        408 => Reason::Timeout,
        409 => Reason::Conflict,
        429 => Reason::RateLimit,
        529 => Reason::Overloaded,
        503 => Reason::Overloaded,
        500..=599 => Reason::ServerError,
        401 | 403 => Reason::AuthError,
        404 => Reason::NotFound,
        400 | 422 => Reason::BadRequest,
        413 => Reason::RequestTooLarge,
        400..=499 => Reason::ClientError,
        _ => return None,
    })
}

/// Exception class names (any module) and what they mean.
const NAME_TABLE: [(&str, Reason); 37] = [
    ("RateLimitError", Reason::RateLimit),
    ("ResourceExhausted", Reason::RateLimit),
    ("TooManyRequests", Reason::RateLimit),
    ("OverloadedError", Reason::Overloaded),
    ("ServiceUnavailableError", Reason::Overloaded),
    ("ServiceUnavailable", Reason::Overloaded),
    ("InternalServerError", Reason::ServerError),
    ("APIError", Reason::ServerError),
    ("ServerError", Reason::ServerError),
    ("APITimeoutError", Reason::Timeout),
    ("TimeoutException", Reason::Timeout),
    ("ReadTimeout", Reason::Timeout),
    ("ConnectTimeout", Reason::Timeout),
    ("WriteTimeout", Reason::Timeout),
    ("PoolTimeout", Reason::Timeout),
    ("Timeout", Reason::Timeout),
    ("DeadlineExceeded", Reason::Timeout),
    ("TimeoutError", Reason::Timeout),
    ("APIConnectionError", Reason::ConnectionError),
    ("ConnectError", Reason::ConnectionError),
    ("RemoteProtocolError", Reason::ConnectionError),
    ("ChunkedEncodingError", Reason::ConnectionError),
    ("ServerDisconnectedError", Reason::ConnectionError),
    ("ClientConnectionError", Reason::ConnectionError),
    ("ConnectionError", Reason::ConnectionError),
    ("ConflictError", Reason::Conflict),
    ("AuthenticationError", Reason::AuthError),
    ("PermissionDeniedError", Reason::AuthError),
    ("Unauthenticated", Reason::AuthError),
    ("PermissionDenied", Reason::AuthError),
    ("BadRequestError", Reason::BadRequest),
    ("UnprocessableEntityError", Reason::BadRequest),
    ("InvalidArgument", Reason::BadRequest),
    ("InvalidRequestError", Reason::BadRequest),
    ("NotFoundError", Reason::NotFound),
    ("NotFound", Reason::NotFound),
    ("RequestTooLargeError", Reason::RequestTooLarge),
];

/// Classifies an error from its MRO class names and optional status code.
pub fn classify_reason(type_names: &[String], status: Option<u16>) -> Reason {
    if let Some(reason) = status.and_then(reason_for_status) {
        return reason;
    }
    for name in type_names {
        if let Some((_, reason)) = NAME_TABLE.iter().find(|(n, _)| n == name) {
            return *reason;
        }
    }
    Reason::UnknownError
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Policy {
    pub max_attempts: u32,
    pub base_delay_ms: u64,
    pub max_delay_ms: u64,
    /// Up to this percentage of the delay is subtracted as jitter (0–100).
    pub jitter_percent: u32,
    pub jitter_key: String,
}

impl Policy {
    pub fn check(&self) -> Result<(), BlockError> {
        let bad = |m: String| Err(BlockError::invalid_argument("retry.invalid_policy", m));
        if self.max_attempts == 0 {
            return bad("max_attempts must be at least 1".to_string());
        }
        if self.jitter_percent > 100 {
            return bad(format!("jitter_percent must be between 0 and 100, got {}", self.jitter_percent));
        }
        if self.base_delay_ms > self.max_delay_ms {
            return bad(format!(
                "base_delay_ms ({}) must not exceed max_delay_ms ({})",
                self.base_delay_ms, self.max_delay_ms
            ));
        }
        Ok(())
    }
}

/// Exponential backoff for `attempt` (1-based: the delay after the first
/// failure is `backoff_ms(1)`), capped at `max_delay_ms`, minus deterministic
/// jitter.
pub fn backoff_ms(attempt: u32, policy: &Policy) -> u64 {
    let exp = attempt.saturating_sub(1).min(63);
    let raw = policy.base_delay_ms.saturating_mul(1u64 << exp).min(policy.max_delay_ms);
    let span = raw.saturating_mul(u64::from(policy.jitter_percent)) / 100;
    if span == 0 {
        return raw;
    }
    let mut hasher = blake3::Hasher::new();
    hasher.update(policy.jitter_key.as_bytes());
    hasher.update(&[0]);
    hasher.update(&attempt.to_be_bytes());
    let digest = hasher.finalize();
    let mut first8 = [0u8; 8];
    first8.copy_from_slice(&digest.as_bytes()[..8]);
    let r = u64::from_be_bytes(first8);
    raw - r % (span + 1)
}

/// Parses `Retry-After` / `retry-after-ms` header values into milliseconds.
/// Only numeric forms are accepted (HTTP dates would need the clock).
pub fn parse_retry_after(retry_after: Option<&str>, retry_after_ms: Option<&str>) -> Option<u64> {
    if let Some(ms) = retry_after_ms.map(str::trim) {
        if let Some(v) = parse_decimal_millis(ms, 1) {
            return Some(v);
        }
    }
    retry_after.map(str::trim).and_then(|s| parse_decimal_millis(s, 1000))
}

/// Parses a non-negative decimal like `1.5` exactly and multiplies by
/// `scale` (1 or 1000), truncating sub-millisecond digits.
fn parse_decimal_millis(s: &str, scale: u64) -> Option<u64> {
    let (int_part, frac_part) = s.split_once('.').unwrap_or((s, ""));
    if int_part.is_empty()
        || !int_part.bytes().all(|b| b.is_ascii_digit())
        || !frac_part.bytes().all(|b| b.is_ascii_digit())
    {
        return None;
    }
    let whole: u64 = int_part.parse().ok()?;
    let mut ms = whole.checked_mul(scale)?;
    if scale == 1000 {
        let frac3: String = frac_part.chars().chain("000".chars()).take(3).collect();
        ms = ms.checked_add(frac3.parse::<u64>().ok()?)?;
    }
    Some(ms)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Decision {
    pub retry: bool,
    pub reason: Reason,
    pub delay_ms: u64,
    pub attempt: u32,
}

/// Decides whether to retry after `attempt` failed attempts (1-based).
pub fn decide(
    reason: Reason,
    attempt: u32,
    retry_after_ms: Option<u64>,
    policy: &Policy,
) -> Result<Decision, BlockError> {
    policy.check()?;
    if attempt == 0 {
        return Err(BlockError::invalid_argument("retry.invalid_attempt", "attempt must be at least 1"));
    }
    let retry = reason.retryable() && attempt < policy.max_attempts;
    let delay_ms = if retry {
        match retry_after_ms {
            Some(ms) => ms.min(policy.max_delay_ms),
            None => backoff_ms(attempt, policy),
        }
    } else {
        0
    };
    Ok(Decision { retry, reason, delay_ms, attempt })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn policy() -> Policy {
        Policy {
            max_attempts: 5,
            base_delay_ms: 1000,
            max_delay_ms: 30_000,
            jitter_percent: 0,
            jitter_key: String::new(),
        }
    }

    fn names(n: &[&str]) -> Vec<String> {
        n.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn classification() {
        assert_eq!(classify_reason(&names(&["RateLimitError", "APIStatusError"]), Some(429)), Reason::RateLimit);
        assert_eq!(classify_reason(&names(&["AuthenticationError"]), None), Reason::AuthError);
        assert_eq!(classify_reason(&names(&["ValueError", "Exception"]), None), Reason::UnknownError);
        assert_eq!(
            classify_reason(&names(&["ConnectionResetError", "ConnectionError", "OSError"]), None),
            Reason::ConnectionError
        );
        assert_eq!(classify_reason(&[], Some(503)), Reason::Overloaded);
        assert_eq!(classify_reason(&[], Some(418)), Reason::ClientError);
        assert_eq!(classify_reason(&names(&["Weird"]), Some(200)), Reason::UnknownError);
    }

    #[test]
    fn backoff_is_exponential_capped_and_deterministic() {
        let p = policy();
        let delays: Vec<u64> = (1..=7).map(|a| backoff_ms(a, &p)).collect();
        assert_eq!(delays, vec![1000, 2000, 4000, 8000, 16000, 30000, 30000]);
        let j = Policy { jitter_percent: 50, jitter_key: "req-1".into(), ..policy() };
        let a = backoff_ms(3, &j);
        assert_eq!(a, backoff_ms(3, &j));
        assert!((2000..=4000).contains(&a));
        assert_eq!(backoff_ms(u32::MAX, &p), 30000);
    }

    #[test]
    fn decisions() {
        let p = policy();
        let d = decide(Reason::RateLimit, 1, None, &p).unwrap();
        assert!(d.retry);
        assert_eq!(d.delay_ms, 1000);
        let d = decide(Reason::RateLimit, 5, None, &p).unwrap();
        assert!(!d.retry);
        let d = decide(Reason::RateLimit, 1, Some(90_000), &p).unwrap();
        assert_eq!(d.delay_ms, 30_000);
        let d = decide(Reason::AuthError, 1, None, &p).unwrap();
        assert!(!d.retry);
        assert_eq!(d.delay_ms, 0);
    }

    #[test]
    fn retry_after_parsing() {
        assert_eq!(parse_retry_after(Some("2"), None), Some(2000));
        assert_eq!(parse_retry_after(Some("1.5"), None), Some(1500));
        assert_eq!(parse_retry_after(Some("0.0005"), None), Some(0));
        assert_eq!(parse_retry_after(Some("Wed, 21 Oct 2015 07:28:00 GMT"), None), None);
        assert_eq!(parse_retry_after(Some("2"), Some("250")), Some(250));
        assert_eq!(parse_retry_after(Some("-1"), None), None);
    }
}
