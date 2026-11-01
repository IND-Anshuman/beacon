//! Extract a JSON object or array from free-form LLM text.
//!
//! The algorithm is deliberately simple and fully specified:
//!
//! 1. **Fences.** Markdown code fences (```` ``` ```` or `~~~`) labelled `json`
//!    — or unlabelled fences whose content starts with `{` or `[` — are *JSON
//!    fences*. If the text contains any, only their contents are candidates,
//!    and each fence must contain exactly one JSON document.
//! 2. **Inline scan.** Otherwise the text is scanned left to right. At each `{`
//!    or `[` a strict JSON value is parsed; on success it becomes a candidate
//!    and scanning resumes after it. A failed parse at a *JSON-like* opener
//!    (`{` followed by `"`, `'` or `}`, or `[` followed by `{`, `[`, `"` or `]`,
//!    whitespace allowed in between) becomes a *malformed candidate* and
//!    scanning resumes after the point of failure. Other failures are prose.
//! 3. **Kind filter.** `auto` keeps objects if there are any, else arrays;
//!    `object` / `array` keep one kind; `any` keeps both.
//! 4. **Selection.** `first`, `last`, `largest` (by length, ties → first) or
//!    `only` (more than one candidate is an error). Selecting a malformed
//!    candidate raises its parse error. `largest` raises if any candidate is
//!    malformed, since its size is unknown.

use crate::error::{BlockError, ErrorKind, TextPos};
use crate::json::{self, JsonError, is_json_ws};
use crate::value::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Select {
    First,
    Last,
    Largest,
    Only,
}

impl Select {
    pub fn parse(s: &str) -> Result<Select, BlockError> {
        match s {
            "first" => Ok(Select::First),
            "last" => Ok(Select::Last),
            "largest" => Ok(Select::Largest),
            "only" => Ok(Select::Only),
            _ => Err(BlockError::invalid_argument(
                "extract_json.invalid_select",
                format!("select must be 'first', 'last', 'largest' or 'only', got '{s}'"),
            )),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Auto,
    Any,
    Object,
    Array,
}

impl Kind {
    pub fn parse(s: &str) -> Result<Kind, BlockError> {
        match s {
            "auto" => Ok(Kind::Auto),
            "any" => Ok(Kind::Any),
            "object" => Ok(Kind::Object),
            "array" => Ok(Kind::Array),
            _ => Err(BlockError::invalid_argument(
                "extract_json.invalid_kind",
                format!("kind must be 'auto', 'any', 'object' or 'array', got '{s}'"),
            )),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    /// The whole input (ignoring surrounding whitespace) is the JSON value.
    Whole,
    /// The value was inside a markdown code fence.
    Fence,
    /// The value was embedded in prose.
    Inline,
}

impl Source {
    pub fn as_str(self) -> &'static str {
        match self {
            Source::Whole => "whole",
            Source::Fence => "fence",
            Source::Inline => "inline",
        }
    }
}

/// A successful extraction. Offsets are code-point offsets into the input.
#[derive(Debug, Clone, PartialEq)]
pub struct Extraction {
    pub value: Value,
    pub start: usize,
    pub end: usize,
    pub source: Source,
    /// Number of candidates that survived the kind filter.
    pub candidates: usize,
}

#[derive(Debug)]
enum Outcome {
    Ok(Value),
    Malformed(JsonError),
}

#[derive(Debug)]
struct Candidate {
    /// Byte span of the value (for malformed candidates: opener → failure).
    start: usize,
    end: usize,
    is_object: bool,
    source: Source,
    outcome: Outcome,
}

/// A fenced code block: byte span of its content.
#[derive(Debug, Clone, Copy)]
pub(crate) struct Fence {
    pub content_start: usize,
    pub content_end: usize,
    pub is_json: bool,
}

/// Finds markdown code fences, line by line. An unclosed fence runs to the end
/// of the text (a truncated response).
pub(crate) fn find_fences(text: &str) -> Vec<Fence> {
    let mut fences = Vec::new();
    let mut open: Option<(u8, usize, String, usize)> = None; // (char, len, info, content_start)
    let mut line_start = 0;
    while line_start <= text.len() {
        let line_end = text[line_start..].find('\n').map_or(text.len(), |i| line_start + i);
        let line = &text[line_start..line_end];
        let indent = line.len() - line.trim_start_matches(' ').len();
        let body = &line[indent..];
        let next_start = line_end + 1;
        if indent <= 3 {
            match &open {
                None => {
                    if let Some((ch, len)) = fence_marker(body) {
                        let info = body[len..].trim().to_string();
                        // Backtick fences may not have backticks in the info string.
                        if !(ch == b'`' && info.contains('`')) {
                            open = Some((ch, len, info, next_start.min(text.len())));
                        }
                    }
                }
                Some((ch, len, info, content_start)) => {
                    if let Some((c2, l2)) = fence_marker(body) {
                        if c2 == *ch && l2 >= *len && body[l2..].trim().is_empty() {
                            let content_end = line_start.max(*content_start);
                            fences.push(make_fence(text, info, *content_start, content_end));
                            open = None;
                        }
                    }
                }
            }
        }
        if line_end == text.len() {
            break;
        }
        line_start = next_start;
    }
    if let Some((_, _, info, content_start)) = open {
        fences.push(make_fence(text, &info, content_start, text.len()));
    }
    fences
}

fn fence_marker(body: &str) -> Option<(u8, usize)> {
    let first = *body.as_bytes().first()?;
    if first != b'`' && first != b'~' {
        return None;
    }
    let len = body.bytes().take_while(|&b| b == first).count();
    (len >= 3).then_some((first, len))
}

fn make_fence(text: &str, info: &str, content_start: usize, content_end: usize) -> Fence {
    let lang = info.split_whitespace().next().unwrap_or("").to_ascii_lowercase();
    let content = text[content_start..content_end].trim_start_matches(|c: char| c.is_ascii_whitespace());
    let is_json = lang == "json" || (lang.is_empty() && (content.starts_with('{') || content.starts_with('[')));
    Fence { content_start, content_end, is_json }
}

/// Whether the opener at `i` looks like the start of real JSON (as opposed to
/// prose such as `{name}` or `[1-3]`).
pub(crate) fn json_like_opener(bytes: &[u8], i: usize) -> bool {
    let next = bytes[i + 1..].iter().copied().find(|b| !is_json_ws(*b));
    match bytes[i] {
        b'{' => matches!(next, Some(b'"' | b'}' | b'\'')),
        b'[' => matches!(next, Some(b'{' | b'[' | b'"' | b']')),
        _ => false,
    }
}

fn scan_inline(text: &str, from: usize, to: usize, source: Source, out: &mut Vec<Candidate>) {
    let bytes = text.as_bytes();
    let mut i = from;
    while i < to {
        let b = bytes[i];
        if b != b'{' && b != b'[' {
            i += 1;
            continue;
        }
        match json::parse_value_at(text, i) {
            Ok((value, end)) if end <= to => {
                out.push(Candidate { start: i, end, is_object: b == b'{', source, outcome: Outcome::Ok(value) });
                i = end;
            }
            Ok(_) => i += 1,
            Err(err) => {
                if json_like_opener(bytes, i) {
                    let resume = err.byte.max(i + 1).min(to);
                    out.push(Candidate {
                        start: i,
                        end: resume,
                        is_object: b == b'{',
                        source,
                        outcome: Outcome::Malformed(err),
                    });
                    i = resume;
                } else {
                    i += 1;
                }
            }
        }
    }
}

fn fence_candidate(text: &str, fence: &Fence) -> Option<Candidate> {
    let content = &text[fence.content_start..fence.content_end];
    let lead = content.len() - content.trim_start_matches(|c: char| c.is_ascii_whitespace()).len();
    let trimmed = content.trim_matches(|c: char| c.is_ascii_whitespace());
    let start = fence.content_start + lead;
    let first = *trimmed.as_bytes().first()?;
    let is_object = first == b'{';
    if first != b'{' && first != b'[' {
        let found = crate::error::describe_char(trimmed.chars().next()?);
        return Some(Candidate {
            start,
            end: start + trimmed.len(),
            is_object: false,
            source: Source::Fence,
            outcome: Outcome::Malformed(JsonError {
                code: "json.expected_value",
                message: format!("expected a JSON object or array in code fence, found {found}"),
                byte: start,
            }),
        });
    }
    let outcome = match json::parse_document(trimmed) {
        Ok(v) => Outcome::Ok(v),
        Err(e) => Outcome::Malformed(JsonError { byte: e.byte + start, ..e }),
    };
    Some(Candidate { start, end: start + trimmed.len(), is_object, source: Source::Fence, outcome })
}

fn malformed_error(text: &str, err: &JsonError) -> BlockError {
    BlockError::at(ErrorKind::Malformed, err.code, err.message.clone(), text, err.byte)
}

/// Runs extraction. Returns `Ok(None)` when no candidate exists at all.
pub fn extract(text: &str, select: Select, kind: Kind) -> Result<Option<Extraction>, BlockError> {
    let fences: Vec<Fence> = find_fences(text).into_iter().filter(|f| f.is_json).collect();
    let mut candidates = Vec::new();
    if fences.is_empty() {
        scan_inline(text, 0, text.len(), Source::Inline, &mut candidates);
    } else {
        candidates.extend(fences.iter().filter_map(|f| fence_candidate(text, f)));
    }

    let want_objects = match kind {
        Kind::Object => Some(true),
        Kind::Array => Some(false),
        Kind::Any => None,
        Kind::Auto => Some(candidates.iter().any(|c| c.is_object)),
    };
    let kept: Vec<Candidate> =
        candidates.into_iter().filter(|c| want_objects.is_none_or(|w| c.is_object == w)).collect();

    if kept.is_empty() {
        return Ok(None);
    }

    let count = kept.len();
    let chosen = match select {
        Select::First => &kept[0],
        Select::Last => &kept[count - 1],
        Select::Only => {
            if count > 1 {
                return Err(BlockError::at(
                    ErrorKind::Malformed,
                    "extract_json.multiple_candidates",
                    format!("expected exactly one JSON value, found {count}; the second one starts"),
                    text,
                    kept[1].start,
                ));
            }
            &kept[0]
        }
        Select::Largest => {
            if let Some(bad) = kept.iter().find(|c| matches!(c.outcome, Outcome::Malformed(_))) {
                if let Outcome::Malformed(err) = &bad.outcome {
                    return Err(malformed_error(text, err));
                }
            }
            let mut best = &kept[0];
            for c in &kept[1..] {
                if text[c.start..c.end].chars().count() > text[best.start..best.end].chars().count() {
                    best = c;
                }
            }
            best
        }
    };

    match &chosen.outcome {
        Outcome::Malformed(err) => Err(malformed_error(text, err)),
        Outcome::Ok(value) => {
            let source = if chosen.source == Source::Inline
                && text[..chosen.start].bytes().all(is_json_ws)
                && text[chosen.end..].bytes().all(is_json_ws)
            {
                Source::Whole
            } else {
                chosen.source
            };
            Ok(Some(Extraction {
                value: value.clone(),
                start: TextPos::from_byte(text, chosen.start).offset,
                end: TextPos::from_byte(text, chosen.end).offset,
                source,
                candidates: count,
            }))
        }
    }
}

/// Like [`extract`], but a missing value is a `NoJSONFoundError`.
pub fn extract_required(text: &str, select: Select, kind: Kind) -> Result<Extraction, BlockError> {
    extract(text, select, kind)?.ok_or_else(|| {
        let what = match kind {
            Kind::Object => "no JSON object found in text",
            Kind::Array => "no JSON array found in text",
            Kind::Auto | Kind::Any => "no JSON object or array found in text",
        };
        BlockError::new(ErrorKind::NoJsonFound, "json.not_found", what)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn get(text: &str) -> Value {
        extract_required(text, Select::First, Kind::Auto).unwrap().value
    }

    fn obj(pairs: Vec<(&str, Value)>) -> Value {
        Value::Object(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
    }

    #[test]
    fn prose_and_fences() {
        let expected = obj(vec![("intent", Value::Str("cancel".into()))]);
        assert_eq!(get(r#"The user wants this: {"intent": "cancel"}"#), expected);
        assert_eq!(get("```json\n{\"intent\": \"cancel\"}\n```"), expected);
        assert_eq!(get("Sure!\n```\n{\"intent\": \"cancel\"}\n```\nDone."), expected);
        assert_eq!(get("~~~json\n{\"intent\": \"cancel\"}\n~~~"), expected);
    }

    #[test]
    fn auto_prefers_objects_over_citation_arrays() {
        let v = get(r#"See [1] and [2]. Result: {"a": 1}"#);
        assert_eq!(v, obj(vec![("a", Value::Int(1))]));
        let v = get("Result: [1, 2, 3]");
        assert_eq!(v, Value::Array(vec![Value::Int(1), Value::Int(2), Value::Int(3)]));
    }

    #[test]
    fn malformed_is_reported_with_position() {
        let err = extract_required(r#"The user wants to {"intent": cancel"#, Select::First, Kind::Auto).unwrap_err();
        assert_eq!(err.kind, ErrorKind::Malformed);
        assert_eq!(err.code, "json.expected_value");
        assert_eq!(err.position.unwrap().offset, 29);
    }

    #[test]
    fn truncated_output_does_not_yield_inner_object() {
        let err = extract_required(r#"{"items": [{"a": 1}, {"b": 2}, {"c": "#, Select::First, Kind::Auto).unwrap_err();
        assert_eq!(err.code, "json.unexpected_end");
    }

    #[test]
    fn template_like_braces_are_prose() {
        let v = get(r#"Use {name} here: {"ok": true}"#);
        assert_eq!(v, obj(vec![("ok", Value::Bool(true))]));
        assert!(extract("Hello {name}", Select::First, Kind::Auto).unwrap().is_none());
    }

    #[test]
    fn selection_modes() {
        let text = r#"{"a": 1} then {"bb": [1, 2, 3]} then {"c": 3}"#;
        let pick = |s| extract_required(text, s, Kind::Auto).unwrap().value;
        assert_eq!(pick(Select::First), obj(vec![("a", Value::Int(1))]));
        assert_eq!(pick(Select::Last), obj(vec![("c", Value::Int(3))]));
        assert_eq!(
            pick(Select::Largest),
            obj(vec![("bb", Value::Array(vec![Value::Int(1), Value::Int(2), Value::Int(3)]))])
        );
        let err = extract_required(text, Select::Only, Kind::Auto).unwrap_err();
        assert_eq!(err.code, "extract_json.multiple_candidates");
    }

    #[test]
    fn whole_source_and_offsets() {
        let e = extract_required("  {\"é\": 1}  ", Select::First, Kind::Auto).unwrap();
        assert_eq!(e.source, Source::Whole);
        assert_eq!((e.start, e.end), (2, 10));
    }

    #[test]
    fn unclosed_fence_is_truncated_json() {
        let err = extract_required("```json\n{\"a\": [1, 2", Select::First, Kind::Auto).unwrap_err();
        assert_eq!(err.code, "json.unexpected_end");
    }

    #[test]
    fn fences_take_priority_over_prose() {
        let text = "Example: {\"x\": 0}\n```json\n{\"real\": 1}\n```";
        assert_eq!(get(text), obj(vec![("real", Value::Int(1))]));
    }

    #[test]
    fn not_found() {
        let err = extract_required("No JSON here at all", Select::First, Kind::Auto).unwrap_err();
        assert_eq!(err.kind, ErrorKind::NoJsonFound);
    }
}
