//! Citation extraction.
//!
//! Finds the citation markers models emit in prose and reports each as a span,
//! mirroring the shape and mechanics of [`crate::redact::detect`]. It is
//! deterministic and provider-agnostic: it reads plain text and never calls a
//! model. A provider-specific helper for structured citation blocks (e.g.
//! Anthropic's `citations` field) belongs in that integration, not here.
//!
//! Three kinds are recognized:
//!
//! * `numeric` — bracketed numeric markers: `[1]`, `[1, 2]`, `[1-3]`. `ref` is
//!   the bracket contents (whitespace trimmed); `text` is the whole `[...]`.
//! * `footnote` — Markdown footnote references: `[^id]`. `ref` is the id.
//! * `url` — inline `http`/`https` URLs. `ref` equals `text` (the URL, with
//!   trailing sentence punctuation trimmed).
//!
//! Matches are merged exactly as redaction merges them: sorted by start offset,
//! then longer first, then kind priority, keeping only non-overlapping spans
//! (so a `[1]` inside a URL is dropped in favour of the URL).

use std::sync::LazyLock;

use regex::Regex;

use crate::error::BlockError;

/// The citation kinds, in priority order.
pub const ALL_KINDS: [&str; 3] = ["numeric", "footnote", "url"];

/// A detected citation. Offsets are code points; `text` is `input[start..end]`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Citation {
    pub kind: &'static str,
    /// The reference the marker points to (the number list, footnote id, or
    /// the URL itself).
    pub reference: String,
    pub start: usize,
    pub end: usize,
    pub text: String,
}

/// Validates a requested kind against [`ALL_KINDS`].
pub fn check_kind(kind: &str) -> Result<(), BlockError> {
    if ALL_KINDS.contains(&kind) {
        Ok(())
    } else {
        Err(BlockError::invalid_argument(
            "citations.invalid_kind",
            format!("kind must be one of 'numeric', 'footnote', 'url', got '{kind}'"),
        ))
    }
}

struct Detector {
    kind: &'static str,
    regex: Regex,
    /// Capture group holding the `ref` (0 = the whole match).
    ref_group: usize,
    /// Trim trailing sentence punctuation from the matched span (for URLs).
    trim_url: bool,
}

// Numeric markers: one or more numbers separated by ',' or '-', optionally
// spaced, inside brackets. Group 1 is the inside.
const NUMERIC: &str = r"\[(\s*[0-9]+(?:\s*[,\-]\s*[0-9]+)*\s*)\]";
// Markdown footnote reference: group 1 is the id (no whitespace or ']').
const FOOTNOTE: &str = r"\[\^([^\]\s]+)\]";
// Inline URL: stop at whitespace, brackets/braces, quotes, backtick, pipe,
// backslash and angle brackets. Trailing punctuation is trimmed afterwards.
const URL: &str = "(?i)https?://[^\\s<>\\[\\]{}\"'|\\\\`]+";

static DETECTORS: LazyLock<Result<Vec<Detector>, String>> = LazyLock::new(|| {
    Ok(vec![
        Detector { kind: "numeric", regex: Regex::new(NUMERIC).map_err(|e| e.to_string())?, ref_group: 1, trim_url: false },
        Detector { kind: "footnote", regex: Regex::new(FOOTNOTE).map_err(|e| e.to_string())?, ref_group: 1, trim_url: false },
        Detector { kind: "url", regex: Regex::new(URL).map_err(|e| e.to_string())?, ref_group: 0, trim_url: true },
    ])
});

fn detectors() -> Result<&'static [Detector], BlockError> {
    match &*DETECTORS {
        Ok(v) => Ok(v),
        Err(e) => Err(BlockError::invalid_argument("citations.internal", format!("internal error: {e}"))),
    }
}

/// Trims trailing sentence punctuation from a URL span. A closing paren is only
/// trimmed when the span has no opening paren (so `…/Foo_(bar)` is kept whole).
fn trim_url_end(text: &str, start: usize, mut end: usize) -> usize {
    loop {
        let seg = &text[start..end];
        let Some(last) = seg.chars().next_back() else { break };
        let drop = matches!(last, '.' | ',' | ';' | ':' | '!' | '?') || (last == ')' && !seg.contains('('));
        if !drop {
            break;
        }
        end -= last.len_utf8();
        if end <= start {
            break;
        }
    }
    end
}

struct RawMatch {
    start: usize,
    end: usize,
    priority: usize,
    kind: &'static str,
    reference: String,
}

fn find(text: &str, kinds: &[&str]) -> Result<Vec<RawMatch>, BlockError> {
    for k in kinds {
        check_kind(k)?;
    }
    let mut raw = Vec::new();
    for (priority, det) in detectors()?.iter().enumerate() {
        if !kinds.contains(&det.kind) {
            continue;
        }
        for caps in det.regex.captures_iter(text) {
            let Some(whole) = caps.get(0) else { continue };
            let start = whole.start();
            let end = if det.trim_url { trim_url_end(text, start, whole.end()) } else { whole.end() };
            if start >= end {
                continue;
            }
            let reference = if det.trim_url {
                text[start..end].to_string()
            } else {
                caps.get(det.ref_group).map(|m| m.as_str().trim().to_string()).unwrap_or_default()
            };
            raw.push(RawMatch { start, end, priority, kind: det.kind, reference });
        }
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

/// Extracts citations of the requested `kinds`, ordered by position.
pub fn extract(text: &str, kinds: &[&str]) -> Result<Vec<Citation>, BlockError> {
    let matches = find(text, kinds)?;
    let mut out = Vec::with_capacity(matches.len());
    // Convert byte offsets to code points incrementally.
    let mut last_byte = 0;
    let mut last_cp = 0;
    for m in matches {
        let start = last_cp + text[last_byte..m.start].chars().count();
        let end = start + text[m.start..m.end].chars().count();
        last_byte = m.end;
        last_cp = end;
        out.push(Citation { kind: m.kind, reference: m.reference, start, end, text: text[m.start..m.end].to_string() });
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn all(text: &str) -> Vec<Citation> {
        extract(text, &ALL_KINDS).unwrap()
    }

    #[test]
    fn numeric_markers() {
        let c = all("See [1] and [2, 3] and the range [4-6].");
        let refs: Vec<_> = c.iter().map(|x| (x.kind, x.reference.as_str(), x.text.as_str())).collect();
        assert_eq!(
            refs,
            vec![("numeric", "1", "[1]"), ("numeric", "2, 3", "[2, 3]"), ("numeric", "4-6", "[4-6]")]
        );
    }

    #[test]
    fn footnote_refs() {
        let c = all("As shown[^note1] and also[^2].");
        assert_eq!(c.len(), 2);
        assert_eq!((c[0].kind, c[0].reference.as_str()), ("footnote", "note1"));
        assert_eq!((c[1].kind, c[1].reference.as_str()), ("footnote", "2"));
    }

    #[test]
    fn urls_trim_trailing_punctuation() {
        let c = all("See https://example.com/a, and (https://example.org/b).");
        assert_eq!(c[0].text, "https://example.com/a");
        assert_eq!(c[0].reference, "https://example.com/a");
        assert_eq!(c[1].text, "https://example.org/b");
    }

    #[test]
    fn url_keeps_balanced_parens() {
        let c = all("ref https://en.wikipedia.org/wiki/Foo_(bar) end");
        assert_eq!(c[0].text, "https://en.wikipedia.org/wiki/Foo_(bar)");
    }

    #[test]
    fn url_ends_at_a_bracket_marker() {
        // A URL stops at '[', so a marker appended to a URL stays a separate
        // citation rather than being swallowed into the URL.
        let c = all("https://example.com/p[1]/x");
        assert_eq!(c[0].kind, "url");
        assert_eq!(c[0].text, "https://example.com/p");
        assert_eq!(c[1].kind, "numeric");
        assert_eq!(c[1].text, "[1]");
    }

    #[test]
    fn kinds_filter() {
        let text = "[1] [^a] https://x.io";
        assert!(extract(text, &["numeric"]).unwrap().iter().all(|c| c.kind == "numeric"));
        assert_eq!(extract(text, &["url"]).unwrap().len(), 1);
        assert_eq!(extract(text, &[]).unwrap().len(), 0);
    }

    #[test]
    fn invalid_kind_is_an_error() {
        assert_eq!(extract("x", &["bogus"]).unwrap_err().code, "citations.invalid_kind");
    }

    #[test]
    fn offsets_are_code_points() {
        let c = all("é [1] é [2]");
        assert_eq!((c[0].start, c[0].end), (2, 5));
        assert_eq!((c[1].start, c[1].end), (8, 11));
    }

    #[test]
    fn ordered_by_position_across_kinds() {
        let c = all("start https://a.io then [1] then[^f] end");
        let kinds: Vec<_> = c.iter().map(|x| x.kind).collect();
        assert_eq!(kinds, vec!["url", "numeric", "footnote"]);
        assert!(c.windows(2).all(|w| w[0].start <= w[1].start));
    }

    #[test]
    fn no_citations_in_plain_text() {
        assert!(all("just some ordinary prose without markers").is_empty());
    }
}
