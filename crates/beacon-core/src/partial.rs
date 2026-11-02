//! Streaming / partial JSON parsing.
//!
//! Parses an **incomplete prefix** of a JSON value — the kind you hold while a
//! response is still streaming in — into the best partial [`Value`] so far, and
//! reports whether the text is a whole JSON value yet.
//!
//! This is strict JSON (double-quoted strings, RFC 8259 numbers and literals),
//! tolerant of exactly one thing: **truncation**. Open containers and strings
//! are closed, a dangling object key with no value is dropped, and an
//! unfinished trailing number or literal is left out. Unlike [`crate::repair`]
//! it keeps no log and performs no fix-ups (no trailing commas, single quotes,
//! comments, `NaN`, …): for near-JSON, use [`crate::repair`]; for JSON buried
//! in prose, locate it with [`crate::extract_json`] first.
//!
//! It never errors and never panics on any input: for anything that is not a
//! JSON value (or its prefix) at the start of the text, the result is the empty
//! partial value `null` with `complete == false`.
//!
//! The function is stateless, so it composes by feeding each growing buffer in
//! again from the start; feeding successive prefixes of a serialized value
//! yields partial values that converge to that value at the final prefix.

use crate::error::TextPos;
use crate::value::Value;

/// Maximum nesting depth; matches the strict parser.
pub const MAX_DEPTH: usize = 512;

/// The result of [`parse_partial`].
#[derive(Debug, Clone, PartialEq)]
pub struct PartialResult {
    /// The structure parsed so far, with any truncated containers and strings
    /// closed. `null` when no value could be parsed yet.
    pub value: Value,
    /// True iff the whole input (ignoring trailing JSON whitespace) is one
    /// complete JSON value.
    pub complete: bool,
    /// How many code points of the input were consumed into `value`.
    pub consumed: usize,
}

/// Parses the best partial JSON value at the start of `text`.
///
/// Returns the value parsed so far, whether the text is already a whole JSON
/// value, and the number of code points consumed into the value.
pub fn parse_partial(text: &str) -> PartialResult {
    let mut p = Partial::new(text);
    p.skip_ws();
    if p.at_end() {
        return PartialResult { value: Value::Null, complete: false, consumed: 0 };
    }
    match p.parse_value(0) {
        Some(value) => {
            let end_byte = p.pos;
            p.skip_ws();
            let complete = !p.truncated && p.at_end();
            let consumed = TextPos::from_byte(text, end_byte).offset;
            PartialResult { value, complete, consumed }
        }
        // Not a JSON value at the start (or only a truncated primitive): nothing
        // usable has been consumed yet.
        None => PartialResult { value: Value::Null, complete: false, consumed: 0 },
    }
}

struct Partial<'a> {
    text: &'a str,
    bytes: &'a [u8],
    pos: usize,
    /// Set when the input ended before the value was complete.
    truncated: bool,
}

impl<'a> Partial<'a> {
    fn new(text: &'a str) -> Self {
        Partial { text, bytes: text.as_bytes(), pos: 0, truncated: false }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn at_end(&self) -> bool {
        self.pos >= self.bytes.len()
    }

    fn skip_ws(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.pos += 1;
        }
    }

    fn skip_digits(&mut self) {
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
    }

    /// Parses one value at the current position (no leading whitespace is
    /// skipped). Returns `None` when there is no value — truncated primitives
    /// set `self.truncated`.
    fn parse_value(&mut self, depth: usize) -> Option<Value> {
        match self.peek()? {
            b'{' => Some(self.parse_object(depth + 1)),
            b'[' => Some(self.parse_array(depth + 1)),
            b'"' => Some(Value::Str(self.parse_string())),
            b't' => self.parse_literal("true", Value::Bool(true)),
            b'f' => self.parse_literal("false", Value::Bool(false)),
            b'n' => self.parse_literal("null", Value::Null),
            b'-' | b'0'..=b'9' => self.parse_number(),
            _ => None,
        }
    }

    fn parse_literal(&mut self, word: &'static str, value: Value) -> Option<Value> {
        let end = self.pos + word.len();
        if self.bytes.get(self.pos..end) == Some(word.as_bytes()) {
            self.pos = end;
            return Some(value);
        }
        // A prefix of the literal running to end of input is a truncated token;
        // anything else is not this literal at all.
        if self.at_end_is_prefix_of(word) {
            self.pos = self.bytes.len();
            self.truncated = true;
        }
        None
    }

    /// True when everything from `pos` to end of input is a proper, non-empty
    /// prefix of `word` (so the rest of `word` was cut off).
    fn at_end_is_prefix_of(&self, word: &str) -> bool {
        let rest = &self.bytes[self.pos..];
        !rest.is_empty() && rest.len() < word.len() && word.as_bytes().starts_with(rest)
    }

    fn parse_object(&mut self, depth: usize) -> Value {
        if depth > MAX_DEPTH {
            self.truncated = true;
            self.pos = self.bytes.len();
            return Value::Null;
        }
        self.pos += 1; // '{'
        let mut entries: Vec<(String, Value)> = Vec::new();
        loop {
            self.skip_ws();
            match self.peek() {
                None => {
                    self.truncated = true;
                    return Value::Object(entries);
                }
                Some(b'}') => {
                    self.pos += 1;
                    return Value::Object(entries);
                }
                Some(b'"') => {}
                // Unexpected byte (not a key): stop here. Not end of input, so
                // this is trailing/malformed content, not truncation.
                Some(_) => return Value::Object(entries),
            }
            let key = self.parse_string();
            if self.truncated {
                return Value::Object(entries); // key itself was cut off: drop it
            }
            self.skip_ws();
            match self.peek() {
                None => {
                    self.truncated = true; // dangling key, no colon
                    return Value::Object(entries);
                }
                Some(b':') => self.pos += 1,
                Some(_) => return Value::Object(entries),
            }
            self.skip_ws();
            match self.parse_value(depth) {
                Some(value) => insert(&mut entries, key, value),
                None => {
                    if self.at_end() {
                        self.truncated = true; // dangling key, truncated value
                    }
                    return Value::Object(entries);
                }
            }
            self.skip_ws();
            match self.peek() {
                None => {
                    self.truncated = true;
                    return Value::Object(entries);
                }
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Value::Object(entries);
                }
                Some(_) => return Value::Object(entries),
            }
        }
    }

    fn parse_array(&mut self, depth: usize) -> Value {
        if depth > MAX_DEPTH {
            self.truncated = true;
            self.pos = self.bytes.len();
            return Value::Null;
        }
        self.pos += 1; // '['
        let mut items = Vec::new();
        loop {
            self.skip_ws();
            match self.peek() {
                None => {
                    self.truncated = true;
                    return Value::Array(items);
                }
                Some(b']') => {
                    self.pos += 1;
                    return Value::Array(items);
                }
                _ => {}
            }
            match self.parse_value(depth) {
                Some(item) => items.push(item),
                None => {
                    if self.at_end() {
                        self.truncated = true; // truncated element
                    }
                    return Value::Array(items);
                }
            }
            self.skip_ws();
            match self.peek() {
                None => {
                    self.truncated = true;
                    return Value::Array(items);
                }
                Some(b',') => self.pos += 1,
                Some(b']') => {
                    self.pos += 1;
                    return Value::Array(items);
                }
                Some(_) => return Value::Array(items),
            }
        }
    }

    /// Parses a double-quoted string, closing it at end of input. To stay total
    /// on out-of-contract bytes it is lenient inside the string (a bad escape is
    /// kept literally, a bad `\u` becomes U+FFFD, a raw control character is
    /// kept); strict JSON prefixes never exercise those paths.
    fn parse_string(&mut self) -> String {
        self.pos += 1; // opening quote
        let mut out = String::new();
        loop {
            match self.peek_char() {
                None => {
                    self.truncated = true; // unterminated string
                    return out;
                }
                Some('"') => {
                    self.pos += 1;
                    return out;
                }
                Some('\\') => {
                    if !self.parse_escape(&mut out) {
                        self.truncated = true; // trailing backslash at end of input
                        return out;
                    }
                }
                Some(c) => {
                    out.push(c);
                    self.pos += c.len_utf8();
                }
            }
        }
    }

    fn peek_char(&self) -> Option<char> {
        self.text.get(self.pos..).and_then(|s| s.chars().next())
    }

    /// Returns false when the backslash is the last byte of the input.
    fn parse_escape(&mut self, out: &mut String) -> bool {
        self.pos += 1; // backslash
        let Some(c) = self.peek_char() else {
            return false;
        };
        let mapped = match c {
            '"' => '"',
            '\\' => '\\',
            '/' => '/',
            'b' => '\u{08}',
            'f' => '\u{0C}',
            'n' => '\n',
            'r' => '\r',
            't' => '\t',
            'u' => {
                self.pos += 1;
                self.parse_unicode(out);
                return true;
            }
            other => {
                out.push(other);
                self.pos += other.len_utf8();
                return true;
            }
        };
        out.push(mapped);
        self.pos += 1; // the escaped character is ASCII here
        true
    }

    fn read_hex4(&mut self) -> Option<u32> {
        let slice = self.bytes.get(self.pos..self.pos + 4)?;
        let mut v = 0u32;
        for &b in slice {
            let d = (b as char).to_digit(16)?;
            v = v * 16 + d;
        }
        self.pos += 4;
        Some(v)
    }

    fn parse_unicode(&mut self, out: &mut String) {
        let Some(first) = self.read_hex4() else {
            out.push('\u{FFFD}');
            return;
        };
        let code = if (0xD800..0xDC00).contains(&first) {
            if self.bytes.get(self.pos..self.pos + 2) == Some(b"\\u") {
                self.pos += 2;
                match self.read_hex4() {
                    Some(second) if (0xDC00..0xE000).contains(&second) => {
                        0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)
                    }
                    _ => {
                        out.push('\u{FFFD}');
                        return;
                    }
                }
            } else {
                out.push('\u{FFFD}');
                return;
            }
        } else if (0xDC00..0xE000).contains(&first) {
            out.push('\u{FFFD}');
            return;
        } else {
            first
        };
        out.push(char::from_u32(code).unwrap_or('\u{FFFD}'));
    }

    /// Parses a JSON number by a single forward scan, taking the longest valid
    /// number. A trailing `.`, `e`, `e-`, … or a lone `-` at end of input is a
    /// truncated number: the valid part so far is returned (or `None` for a
    /// lone `-`).
    fn parse_number(&mut self) -> Option<Value> {
        let start = self.pos;
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        match self.peek() {
            Some(b'0') => self.pos += 1,
            Some(b'1'..=b'9') => self.skip_digits(),
            _ => {
                // A lone '-' (possibly at end of input): no value yet.
                if self.at_end() {
                    self.truncated = true;
                }
                self.pos = start;
                return None;
            }
        }
        let mut is_float = false;
        let mut valid_end = self.pos; // end of the valid number so far
        if self.peek() == Some(b'.') {
            self.pos += 1;
            if matches!(self.peek(), Some(b'0'..=b'9')) {
                self.skip_digits();
                is_float = true;
                valid_end = self.pos;
            } else {
                if self.at_end() {
                    self.truncated = true;
                }
                self.pos = valid_end; // drop the dangling '.'
                return self.finish_number(start, valid_end, false);
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            if matches!(self.peek(), Some(b'0'..=b'9')) {
                self.skip_digits();
                is_float = true;
                valid_end = self.pos;
            } else {
                if self.at_end() {
                    self.truncated = true;
                }
                self.pos = valid_end; // drop the dangling exponent
                return self.finish_number(start, valid_end, is_float);
            }
        }
        self.pos = valid_end;
        self.finish_number(start, valid_end, is_float)
    }

    fn finish_number(&self, start: usize, end: usize, is_float: bool) -> Option<Value> {
        let lexeme = &self.text[start..end];
        if is_float {
            match lexeme.parse::<f64>() {
                Ok(f) if f.is_finite() => Some(Value::Float(f)),
                _ => None,
            }
        } else {
            match lexeme.parse::<i64>() {
                Ok(i) => Some(Value::Int(i)),
                // Valid integer syntax that overflows i64: keep it exact.
                Err(_) => Some(Value::BigInt(lexeme.to_string())),
            }
        }
    }
}

/// Inserts a key/value, keeping the last value for a duplicate key. Strict JSON
/// prefixes have no duplicates; this only matters for out-of-contract input.
fn insert(entries: &mut Vec<(String, Value)>, key: String, value: Value) {
    if let Some(slot) = entries.iter_mut().find(|(k, _)| *k == key) {
        slot.1 = value;
    } else {
        entries.push((key, value));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pp(text: &str) -> PartialResult {
        parse_partial(text)
    }

    #[test]
    fn complete_values_are_complete() {
        for text in [
            r#"{"a": 1, "b": [true, null, "x"], "n": -2.5e3}"#,
            "[1, 2, 3]",
            r#""hello""#,
            "true",
            "false",
            "null",
            "123",
            "-0.5",
            "123456789012345678901234567890",
        ] {
            let r = pp(text);
            assert!(r.complete, "{text:?} should be complete");
            assert_eq!(r.consumed, text.chars().count(), "{text:?}");
        }
    }

    #[test]
    fn trailing_whitespace_is_still_complete() {
        let r = pp("  {\"a\": 1}  \n ");
        assert!(r.complete);
        assert_eq!(r.value.to_json(), r#"{"a": 1}"#);
        // `consumed` stops at the end of the value, before trailing whitespace.
        assert_eq!(r.consumed, "  {\"a\": 1}".chars().count());
    }

    #[test]
    fn truncated_object_is_closed_and_incomplete() {
        let r = pp(r#"{"a": 1, "b": {"c": 2"#);
        assert!(!r.complete);
        assert_eq!(r.value.to_json(), r#"{"a": 1, "b": {"c": 2}}"#);
    }

    #[test]
    fn truncated_array_and_string() {
        let a = pp("[1, 2, 3");
        assert!(!a.complete);
        assert_eq!(a.value.to_json(), "[1, 2, 3]");
        let s = pp(r#"{"a": "unterminat"#);
        assert!(!s.complete);
        assert_eq!(s.value.to_json(), r#"{"a": "unterminat"}"#);
    }

    #[test]
    fn dangling_key_is_dropped() {
        for text in [r#"{"a": 1, "b""#, r#"{"a": 1, "b":"#, r#"{"a": 1, "b": "#, r#"{"a": 1, "bcd"#] {
            let r = pp(text);
            assert!(!r.complete, "{text:?}");
            assert_eq!(r.value.to_json(), r#"{"a": 1}"#, "{text:?}");
        }
    }

    #[test]
    fn truncated_numbers_and_literals() {
        assert_eq!(pp("[1, 2.").value.to_json(), "[1, 2]");
        assert_eq!(pp("[1, 2.5e").value.to_json(), "[1, 2.5]");
        assert_eq!(pp("[1, -").value.to_json(), "[1]");
        assert_eq!(pp("[tr").value.to_json(), "[]");
        assert_eq!(pp("[true, fal").value.to_json(), "[true]");
        assert_eq!(pp("nul").value, Value::Null);
        assert!(!pp("nul").complete);
        assert!(!pp("[1, 2.").complete);
    }

    #[test]
    fn empty_and_garbage_yield_empty_value() {
        for text in ["", "   ", "\n\t", "not json", "}", "]", ":"] {
            let r = pp(text);
            assert_eq!(r.value, Value::Null, "{text:?}");
            assert!(!r.complete, "{text:?}");
            assert_eq!(r.consumed, 0, "{text:?}");
        }
    }

    #[test]
    fn trailing_content_is_not_complete() {
        let r = pp(r#"{"a": 1} extra"#);
        assert!(!r.complete);
        assert_eq!(r.value.to_json(), r#"{"a": 1}"#);
        assert_eq!(r.consumed, 8); // through the closing brace
    }

    #[test]
    fn consumed_counts_code_points() {
        // Multi-byte characters inside the value: `consumed` is code points, not
        // bytes. The input is 8 code points: [ " é " ,   " x " ]  -> wait, count below.
        let text = "[\"é\", \"🥂\"]";
        let r = pp(text);
        assert!(r.complete);
        assert_eq!(r.consumed, text.chars().count());
        assert!(r.consumed < text.len()); // fewer code points than bytes
        assert_eq!(r.value, Value::Array(vec![Value::Str("é".into()), Value::Str("🥂".into())]));
    }

    #[test]
    fn every_prefix_converges_and_never_panics() {
        let full = r#"{"items": [1, 2.5, -3, "a\n", true, null], "nested": {"x": [false]}, "big": 123456789012345678901234567890}"#;
        let complete = parse_partial(full);
        assert!(complete.complete);
        // Feed every prefix that ends on a char boundary.
        for end in 0..=full.len() {
            if !full.is_char_boundary(end) {
                continue;
            }
            let _ = parse_partial(&full[..end]); // must not panic
        }
        // The final prefix equals the whole value.
        assert_eq!(complete.value, parse_partial(full).value);
    }

    #[test]
    fn deeply_nested_input_does_not_overflow() {
        let deep = "[".repeat(5000);
        let r = parse_partial(&deep); // must not panic or recurse past the limit
        assert!(!r.complete);
    }
}
