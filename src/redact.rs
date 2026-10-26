//! PII and secret detection / redaction.
//!
//! Every detector is a regular expression plus an optional validation step
//! (Luhn for card numbers, range rules for SSNs, digit counts for phone
//! numbers, a real parser for IPv6). Matches from all detectors are merged
//! deterministically:
//!
//! 1. sort by start offset, then longer match first, then detector priority
//!    (the order of [`BUILTIN_LABELS`], then custom patterns in the order
//!    given, then term lists in the order given);
//! 2. keep a match only if it does not overlap one already kept.

use std::net::Ipv6Addr;
use std::sync::LazyLock;

use aho_corasick::{AhoCorasick, AhoCorasickBuilder, MatchKind};
use regex::Regex;

use crate::error::BlockError;

/// Built-in detector labels, in priority order.
pub const BUILTIN_LABELS: [&str; 11] = [
    "private_key",
    "jwt",
    "bearer_token",
    "api_key",
    "aws_access_key",
    "email",
    "credit_card",
    "ssn",
    "phone",
    "ipv6",
    "ipv4",
];

/// Labels enabled by each policy.
pub fn policy_labels(policy: &str) -> Result<&'static [&'static str], BlockError> {
    const SECRETS: &[&str] = &["private_key", "jwt", "bearer_token", "api_key", "aws_access_key"];
    const PII: &[&str] = &["email", "credit_card", "ssn", "phone"];
    const DEFAULT: &[&str] =
        &["private_key", "jwt", "bearer_token", "api_key", "aws_access_key", "email", "credit_card", "ssn", "phone"];
    match policy {
        "default" => Ok(DEFAULT),
        "strict" => Ok(&BUILTIN_LABELS),
        "secrets" => Ok(SECRETS),
        "pii" => Ok(PII),
        "none" => Ok(&[]),
        _ => Err(BlockError::invalid_argument(
            "redact.invalid_policy",
            format!("policy must be 'default', 'strict', 'secrets', 'pii' or 'none', got '{policy}'"),
        )),
    }
}

#[derive(Clone, Copy)]
enum Check {
    None,
    Luhn,
    Ssn,
    Phone,
    Ipv6,
    WordBounded,
    EmailBounded,
}

struct Detector {
    label: &'static str,
    regex: Regex,
    /// Capture group holding the sensitive part (0 = whole match).
    group: usize,
    check: Check,
}

const BUILTIN_PATTERNS: [(&str, &str, usize, Check); 18] = [
    (
        "private_key",
        r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----",
        0,
        Check::None,
    ),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", 0, Check::None),
    ("bearer_token", r"(?i)\bbearer\s+([A-Za-z0-9._~+/-]{20,}=*)", 1, Check::None),
    ("api_key", r"\bsk-ant-[A-Za-z0-9_-]{20,}", 0, Check::None),
    ("api_key", r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}", 0, Check::None),
    ("api_key", r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b", 0, Check::None),
    ("api_key", r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b", 0, Check::None),
    ("api_key", r"\bxox[abprs]-[A-Za-z0-9-]{10,}", 0, Check::None),
    ("api_key", r"\bAIza[0-9A-Za-z_-]{35}", 0, Check::None),
    ("api_key", r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,}", 0, Check::None),
    ("api_key", r"\bhf_[A-Za-z0-9]{30,}", 0, Check::None),
    ("aws_access_key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", 0, Check::None),
    ("email", r"(?i)[\p{L}\p{N}._%+-]+@[\p{L}\p{N}-]+(?:\.[\p{L}\p{N}-]+)*\.\p{L}{2,}\b", 0, Check::EmailBounded),
    ("credit_card", r"\b(?:[0-9][ -]?){12,18}[0-9]\b", 0, Check::Luhn),
    ("ssn", r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b", 0, Check::Ssn),
    ("phone", r"\+[0-9]{1,3}(?:[ .-]?\(?[0-9]{1,4}\)?){2,6}", 0, Check::Phone),
    ("phone", r"(?:\([0-9]{3}\)[ .-]?|[0-9]{3}[ .-])[0-9]{3}[ .-][0-9]{4}\b", 0, Check::Phone),
    ("ipv6", r"(?i)[0-9a-f:]*:[0-9a-f:]*:[0-9a-f:]*", 0, Check::Ipv6),
];

const IPV4: &str =
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\b";

static BUILTINS: LazyLock<Result<Vec<Detector>, String>> = LazyLock::new(|| {
    let mut out = Vec::new();
    for (label, pattern, group, check) in BUILTIN_PATTERNS {
        let regex = Regex::new(pattern).map_err(|e| e.to_string())?;
        out.push(Detector { label, regex, group, check });
    }
    let regex = Regex::new(IPV4).map_err(|e| e.to_string())?;
    out.push(Detector { label: "ipv4", regex, group: 0, check: Check::None });
    Ok(out)
});

fn builtins() -> Result<&'static [Detector], BlockError> {
    match &*BUILTINS {
        Ok(v) => Ok(v),
        Err(e) => Err(BlockError::invalid_argument("redact.internal", format!("internal error: {e}"))),
    }
}

fn luhn(digits: &[u32]) -> bool {
    let mut sum = 0;
    for (i, d) in digits.iter().rev().enumerate() {
        let mut d = *d;
        if i % 2 == 1 {
            d *= 2;
            if d > 9 {
                d -= 9;
            }
        }
        sum += d;
    }
    sum % 10 == 0
}

fn digits_of(s: &str) -> Vec<u32> {
    s.chars().filter_map(|c| c.to_digit(10)).collect()
}

fn passes(check: Check, text: &str, start: usize, end: usize) -> bool {
    let m = &text[start..end];
    let before = text[..start].chars().next_back();
    let after = text[end..].chars().next();
    match check {
        Check::None => true,
        Check::Luhn => {
            let d = digits_of(m);
            (13..=19).contains(&d.len()) && luhn(&d)
        }
        Check::Ssn => {
            let d = digits_of(m);
            if d.len() != 9 {
                return false;
            }
            let area = d[0] * 100 + d[1] * 10 + d[2];
            let group = d[3] * 10 + d[4];
            let serial = d[5] * 1000 + d[6] * 100 + d[7] * 10 + d[8];
            area != 0 && area != 666 && area < 900 && group != 0 && serial != 0
        }
        Check::Phone => {
            let n = digits_of(m).len();
            let range = if m.starts_with('+') { 9..=15 } else { 10..=10 };
            range.contains(&n)
                && !before.is_some_and(|c| c.is_alphanumeric() || matches!(c, '+' | '-' | '.' | '/' | '_'))
                && !after.is_some_and(|c| c.is_alphanumeric() || matches!(c, '-' | '/' | '_'))
        }
        Check::Ipv6 => {
            let hex_digits = m.chars().filter(char::is_ascii_hexdigit).count();
            hex_digits >= 4
                && m.parse::<Ipv6Addr>().is_ok()
                && !before.is_some_and(|c| c.is_alphanumeric())
                && !after.is_some_and(|c| c.is_alphanumeric())
        }
        // The local part may not continue a longer word-ish token on the left.
        Check::EmailBounded => !before.is_some_and(|c| c.is_alphanumeric() || matches!(c, '.' | '_' | '%' | '+' | '-')),
        Check::WordBounded => {
            !before.is_some_and(|c| c.is_alphanumeric() || c == '_')
                && !after.is_some_and(|c| c.is_alphanumeric() || c == '_')
        }
    }
}

/// A detected span. Offsets are code points.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Finding {
    pub label: String,
    pub start: usize,
    pub end: usize,
    pub text: String,
}

/// What to detect.
pub struct Spec<'a> {
    pub labels: Vec<&'a str>,
    /// `(label, regex)` pairs, compiled per call (no caching).
    pub custom: &'a [(String, String)],
    /// `(label, terms)` pairs matched as whole words, ASCII case-insensitive.
    pub terms: &'a [(String, Vec<String>)],
}

pub fn check_label(label: &str) -> Result<(), BlockError> {
    let mut chars = label.chars();
    let ok = matches!(chars.next(), Some('a'..='z')) && chars.all(|c| matches!(c, 'a'..='z' | '0'..='9' | '_'));
    if ok {
        Ok(())
    } else {
        Err(BlockError::invalid_argument("redact.invalid_label", format!("label {label:?} must match [a-z][a-z0-9_]*")))
    }
}

struct RawMatch {
    start: usize,
    end: usize,
    priority: usize,
    label: String,
}

/// Finds all non-overlapping sensitive spans, in order. Byte offsets.
fn find(text: &str, spec: &Spec<'_>) -> Result<Vec<RawMatch>, BlockError> {
    let mut raw = Vec::new();
    let detectors = builtins()?;
    for (priority, label) in BUILTIN_LABELS.iter().enumerate() {
        if !spec.labels.contains(label) {
            continue;
        }
        for det in detectors.iter().filter(|d| d.label == *label) {
            for caps in det.regex.captures_iter(text) {
                let Some(m) = caps.get(det.group) else { continue };
                if m.start() < m.end() && passes(det.check, text, m.start(), m.end()) {
                    raw.push(RawMatch { start: m.start(), end: m.end(), priority, label: det.label.to_string() });
                }
            }
        }
    }
    let mut priority = BUILTIN_LABELS.len();
    for (label, pattern) in spec.custom {
        check_label(label)?;
        let re = Regex::new(pattern).map_err(|_| {
            BlockError::invalid_argument(
                "redact.invalid_pattern",
                format!("invalid regular expression for label '{label}'"),
            )
        })?;
        for m in re.find_iter(text) {
            if m.start() < m.end() {
                raw.push(RawMatch { start: m.start(), end: m.end(), priority, label: label.clone() });
            }
        }
        priority += 1;
    }
    for (label, terms) in spec.terms {
        check_label(label)?;
        let terms: Vec<&String> = terms.iter().filter(|t| !t.is_empty()).collect();
        if terms.is_empty() {
            continue;
        }
        let ac: AhoCorasick = AhoCorasickBuilder::new()
            .match_kind(MatchKind::LeftmostLongest)
            .ascii_case_insensitive(true)
            .build(&terms)
            .map_err(|_| {
                BlockError::invalid_argument("redact.invalid_terms", format!("invalid terms for label '{label}'"))
            })?;
        for m in ac.find_iter(text) {
            if passes(Check::WordBounded, text, m.start(), m.end()) {
                raw.push(RawMatch { start: m.start(), end: m.end(), priority, label: label.clone() });
            }
        }
        priority += 1;
    }

    raw.sort_by(|a, b| a.start.cmp(&b.start).then(b.end.cmp(&a.end)).then(a.priority.cmp(&b.priority)));
    let mut kept: Vec<RawMatch> = Vec::new();
    for m in raw {
        if kept.last().is_none_or(|k| m.start >= k.end) {
            kept.push(m);
        }
    }
    Ok(kept)
}

/// Detects sensitive spans.
pub fn detect(text: &str, spec: &Spec<'_>) -> Result<Vec<Finding>, BlockError> {
    let matches = find(text, spec)?;
    let mut out = Vec::with_capacity(matches.len());
    // Convert byte offsets to code points incrementally.
    let mut last_byte = 0;
    let mut last_cp = 0;
    for m in matches {
        let start = last_cp + text[last_byte..m.start].chars().count();
        let end = start + text[m.start..m.end].chars().count();
        last_byte = m.end;
        last_cp = end;
        out.push(Finding { label: m.label, start, end, text: text[m.start..m.end].to_string() });
    }
    Ok(out)
}

/// Validates a replacement template: only `{label}` and `{hash}` placeholders
/// (and `{{`/`}}` escapes) are allowed.
pub fn check_replacement(replacement: &str) -> Result<(), BlockError> {
    let mut rest = replacement;
    while let Some(i) = rest.find(['{', '}']) {
        let tail = &rest[i..];
        let step = if tail.starts_with("{{") || tail.starts_with("}}") {
            2
        } else if tail.starts_with("{label}") {
            7
        } else if tail.starts_with("{hash}") {
            6
        } else {
            return Err(BlockError::invalid_argument(
                "redact.invalid_replacement",
                "replacement may only contain the placeholders '{label}' and '{hash}' \
                 (write '{{' or '}}' for literal braces)",
            ));
        };
        rest = &tail[step..];
    }
    Ok(())
}

fn render_replacement(replacement: &str, label: &str, matched: &str, out: &mut String) {
    let mut rest = replacement;
    while let Some(i) = rest.find(['{', '}']) {
        out.push_str(&rest[..i]);
        let tail = &rest[i..];
        if let Some(t) = tail.strip_prefix("{{") {
            out.push('{');
            rest = t;
        } else if let Some(t) = tail.strip_prefix("}}") {
            out.push('}');
            rest = t;
        } else if let Some(t) = tail.strip_prefix("{label}") {
            out.push_str(label);
            rest = t;
        } else if let Some(t) = tail.strip_prefix("{hash}") {
            out.push_str(&blake3::hash(matched.as_bytes()).to_hex()[..8]);
            rest = t;
        } else {
            out.push_str(&tail[..1]);
            rest = &tail[1..];
        }
    }
    out.push_str(rest);
}

/// Replaces every detected span with the rendered replacement.
pub fn redact(text: &str, spec: &Spec<'_>, replacement: &str) -> Result<String, BlockError> {
    check_replacement(replacement)?;
    let matches = find(text, spec)?;
    let mut out = String::with_capacity(text.len());
    let mut cursor = 0;
    for m in matches {
        out.push_str(&text[cursor..m.start]);
        render_replacement(replacement, &m.label, &text[m.start..m.end], &mut out);
        cursor = m.end;
    }
    out.push_str(&text[cursor..]);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn r(text: &str, policy: &str) -> String {
        let spec = Spec { labels: policy_labels(policy).unwrap().to_vec(), custom: &[], terms: &[] };
        redact(text, &spec, "[REDACTED:{label}]").unwrap()
    }

    #[test]
    fn basics() {
        assert_eq!(r("Email me at alice@example.com", "default"), "Email me at [REDACTED:email]");
        assert_eq!(r("Card: 4111-1111-1111-1111", "strict"), "Card: [REDACTED:credit_card]");
        assert_eq!(r("Card: 4111-1111-1111-1112", "strict"), "Card: 4111-1111-1111-1112");
        assert_eq!(r("SSN 123-45-6789.", "default"), "SSN [REDACTED:ssn].");
        assert_eq!(r("SSN 000-45-6789.", "default"), "SSN 000-45-6789.");
        assert_eq!(r("Call +1 (555) 123-4567 now", "default"), "Call [REDACTED:phone] now");
        assert_eq!(r("Tél +33 1 23 45 67 89.", "default"), "Tél [REDACTED:phone].");
        assert_eq!(r("zoë@exemple.fr", "default"), "[REDACTED:email]");
        assert_eq!(r("Date 2024-01-15", "default"), "Date 2024-01-15");
        assert_eq!(r("host 10.0.0.1", "default"), "host 10.0.0.1");
        assert_eq!(r("host 10.0.0.1", "strict"), "host [REDACTED:ipv4]");
        assert_eq!(r("at 12:30:45 or 2001:db8::1", "strict"), "at 12:30:45 or [REDACTED:ipv6]");
    }

    #[test]
    fn secrets() {
        let key = "sk-proj-abcdefghijklmnopqrstuvwxyz0123";
        assert_eq!(r(&format!("key={key}"), "secrets"), "key=[REDACTED:api_key]");
        assert_eq!(
            r("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "default"),
            "Authorization: Bearer [REDACTED:bearer_token]"
        );
        assert_eq!(r("AKIAIOSFODNN7EXAMPLE", "default"), "[REDACTED:aws_access_key]");
    }

    #[test]
    fn custom_terms_and_hash() {
        let custom = vec![("employee_id".to_string(), r"EMP-\d{6}".to_string())];
        let terms = vec![("project".to_string(), vec!["Falcon".to_string()])];
        let spec = Spec { labels: vec![], custom: &custom, terms: &terms };
        assert_eq!(
            redact("EMP-123456 on falcon, not Falconry", &spec, "<{label}>").unwrap(),
            "<employee_id> on <project>, not Falconry"
        );
        let a = redact("falcon", &spec, "{hash}").unwrap();
        assert_eq!(a.len(), 8);
        assert_eq!(a, redact("falcon", &spec, "{hash}").unwrap());
        assert!(check_replacement("{oops}").is_err());
    }

    #[test]
    fn detect_offsets_are_code_points() {
        let spec = Spec { labels: vec!["email"], custom: &[], terms: &[] };
        let f = detect("é a@b.co é c@d.io", &spec).unwrap();
        assert_eq!((f[0].start, f[0].end), (2, 8));
        assert_eq!((f[1].start, f[1].end), (11, 17));
    }
}
