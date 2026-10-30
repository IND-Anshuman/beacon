//! A tolerant JSON repairer.
//!
//! Unlike the strict parser in [`crate::json`], this accepts the near-JSON that
//! models actually emit and returns a [`Value`] **plus a complete, ordered log
//! of every change it made**. Nothing is repaired silently: each deviation from
//! strict JSON is recorded as a [`Repair`] with its code-point offset.
//!
//! It is document-oriented: it repairs the JSON value at the start of the
//! (BOM- and comment-stripped) text and ignores trailing content. For JSON
//! buried in prose, locate it with [`crate::extract_json`] first.
//!
//! Truncation — the most common real failure (a response cut off at a token
//! limit) — is handled explicitly: open containers and strings are closed, the
//! result is marked `incomplete`, and the final `truncated` repair names the
//! brackets that were closed.

use crate::error::{BlockError, ErrorKind, TextPos};
use crate::value::{Value, write_json_string};

/// Maximum nesting depth; matches the strict parser.
pub const MAX_DEPTH: usize = 512;

/// One change the repairer made, with the code-point offset where it applied.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Repair {
    pub kind: &'static str,
    pub at: usize,
    pub detail: String,
}

/// The result of [`repair`].
#[derive(Debug, Clone, PartialEq)]
pub struct Repaired {
    pub value: Value,
    pub repairs: Vec<Repair>,
    /// True when the input ended before the JSON was complete.
    pub incomplete: bool,
}

fn no_json() -> BlockError {
    BlockError::new(ErrorKind::NoJsonFound, "json.not_found", "no JSON value found to repair")
}

/// Repairs the JSON value at the start of `text`. Returns [`Repaired`], or a
/// `NoJSONFoundError` if there is no value to repair at all.
pub fn repair(text: &str) -> Result<Repaired, BlockError> {
    let mut r = Repairer::new(text);
    r.strip_bom();
    r.skip_ws_and_comments();
    if r.at_end() {
        return Err(no_json());
    }
    let Some(value) = r.parse_value(0) else {
        return Err(no_json());
    };
    if r.incomplete {
        let at = TextPos::from_byte(text, text.len()).offset;
        let mut detail = String::from("input ended before the JSON value was complete");
        if !r.closed.is_empty() {
            let brackets: String =
                r.closed.iter().map(|c| c.to_string()).collect::<Vec<_>>().join(" ");
            let n = r.closed.len();
            let word = if n == 1 { "container" } else { "containers" };
            detail.push_str(&format!("; closed {n} unterminated {word}: {brackets}"));
        }
        r.repairs.push(Repair { kind: "truncated", at, detail });
    }
    Ok(Repaired { value, repairs: r.repairs, incomplete: r.incomplete })
}

struct Repairer<'a> {
    text: &'a str,
    bytes: &'a [u8],
    pos: usize,
    repairs: Vec<Repair>,
    incomplete: bool,
    /// Brackets closed because of truncation, innermost first.
    closed: Vec<char>,
}

impl<'a> Repairer<'a> {
    fn new(text: &'a str) -> Self {
        Repairer { text, bytes: text.as_bytes(), pos: 0, repairs: Vec::new(), incomplete: false, closed: Vec::new() }
    }

    fn record(&mut self, kind: &'static str, byte: usize, detail: impl Into<String>) {
        let at = TextPos::from_byte(self.text, byte).offset;
        self.repairs.push(Repair { kind, at, detail: detail.into() });
    }

    fn truncate_close(&mut self, bracket: char) {
        self.incomplete = true;
        self.closed.push(bracket);
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn peek_char(&self) -> Option<char> {
        self.text.get(self.pos..).and_then(|s| s.chars().next())
    }

    fn bump(&mut self) {
        self.pos += 1;
    }

    fn bump_char(&mut self) {
        if let Some(c) = self.peek_char() {
            self.pos += c.len_utf8();
        }
    }

    fn at_end(&self) -> bool {
        self.pos >= self.bytes.len()
    }

    fn strip_bom(&mut self) {
        if self.bytes.get(0..3) == Some(&[0xEF, 0xBB, 0xBF]) {
            self.record("bom", 0, "removed UTF-8 byte-order mark");
            self.pos = 3;
        }
    }

    fn skip_ws_and_comments(&mut self) {
        loop {
            let mut moved = false;
            while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
                self.bump();
                moved = true;
            }
            if self.peek() == Some(b'/') {
                match self.bytes.get(self.pos + 1) {
                    Some(b'/') => {
                        let at = self.pos;
                        self.pos += 2;
                        while self.peek().is_some() && self.peek() != Some(b'\n') {
                            self.bump_char();
                        }
                        self.record("comment", at, "removed // line comment");
                        moved = true;
                    }
                    Some(b'*') => {
                        let at = self.pos;
                        self.pos += 2;
                        while self.peek().is_some()
                            && !(self.peek() == Some(b'*') && self.bytes.get(self.pos + 1) == Some(&b'/'))
                        {
                            self.bump_char();
                        }
                        if self.peek().is_some() {
                            self.pos += 2; // consume */
                        } else {
                            self.incomplete = true;
                        }
                        self.record("comment", at, "removed /* */ block comment");
                        moved = true;
                    }
                    _ => {}
                }
            }
            if !moved {
                break;
            }
        }
    }

    fn parse_value(&mut self, depth: usize) -> Option<Value> {
        self.skip_ws_and_comments();
        match self.peek_char()? {
            '{' => Some(self.parse_object(depth + 1)),
            '[' => Some(self.parse_array(depth + 1)),
            '"' | '\'' | '\u{201C}' | '\u{2018}' => Some(Value::Str(self.parse_string())),
            '-' => self.parse_number(),
            c if c.is_ascii_digit() => self.parse_number(),
            c if c.is_ascii_alphabetic() => self.parse_keyword(),
            _ => None,
        }
    }

    fn parse_object(&mut self, depth: usize) -> Value {
        if depth > MAX_DEPTH {
            self.incomplete = true;
            self.pos = self.bytes.len();
            return Value::Null;
        }
        self.bump(); // '{'
        let mut entries: Vec<(String, Value)> = Vec::new();
        loop {
            self.skip_ws_and_comments();
            match self.peek() {
                None => {
                    self.truncate_close('}');
                    return Value::Object(entries);
                }
                Some(b'}') => {
                    self.bump();
                    return Value::Object(entries);
                }
                _ => {}
            }
            let key_byte = self.pos;
            let Some(key) = self.parse_key() else {
                self.truncate_close('}');
                return Value::Object(entries);
            };
            self.skip_ws_and_comments();
            if self.peek() == Some(b':') {
                self.bump();
            } else if self.at_end() {
                self.truncate_close('}'); // dangling key, no colon
                return Value::Object(entries);
            }
            // A missing colon with more text follows: proceed leniently.
            let Some(value) = self.parse_value(depth) else {
                self.truncate_close('}'); // dangling key, no value
                return Value::Object(entries);
            };
            self.insert(&mut entries, key, key_byte, value);
            self.skip_ws_and_comments();
            match self.peek() {
                Some(b',') => {
                    let comma = self.pos;
                    self.bump();
                    self.skip_ws_and_comments();
                    if matches!(self.peek(), Some(b'}') | None) {
                        self.record("trailing_comma", comma, "removed ',' before '}'");
                        if self.peek() == Some(b'}') {
                            self.bump();
                        } else {
                            self.truncate_close('}');
                        }
                        return Value::Object(entries);
                    }
                }
                Some(b'}') => {
                    self.bump();
                    return Value::Object(entries);
                }
                None => {
                    self.truncate_close('}');
                    return Value::Object(entries);
                }
                Some(_) => {} // missing comma: continue leniently
            }
        }
    }

    fn parse_array(&mut self, depth: usize) -> Value {
        if depth > MAX_DEPTH {
            self.incomplete = true;
            self.pos = self.bytes.len();
            return Value::Null;
        }
        self.bump(); // '['
        let mut items = Vec::new();
        loop {
            self.skip_ws_and_comments();
            match self.peek() {
                None => {
                    self.truncate_close(']');
                    return Value::Array(items);
                }
                Some(b']') => {
                    self.bump();
                    return Value::Array(items);
                }
                _ => {}
            }
            let Some(item) = self.parse_value(depth) else {
                self.truncate_close(']');
                return Value::Array(items);
            };
            items.push(item);
            self.skip_ws_and_comments();
            match self.peek() {
                Some(b',') => {
                    let comma = self.pos;
                    self.bump();
                    self.skip_ws_and_comments();
                    if matches!(self.peek(), Some(b']') | None) {
                        self.record("trailing_comma", comma, "removed ',' before ']'");
                        if self.peek() == Some(b']') {
                            self.bump();
                        } else {
                            self.truncate_close(']');
                        }
                        return Value::Array(items);
                    }
                }
                Some(b']') => {
                    self.bump();
                    return Value::Array(items);
                }
                None => {
                    self.truncate_close(']');
                    return Value::Array(items);
                }
                Some(_) => {} // missing comma: continue leniently
            }
        }
    }

    fn insert(&mut self, entries: &mut Vec<(String, Value)>, key: String, key_byte: usize, value: Value) {
        if let Some(slot) = entries.iter_mut().find(|(k, _)| *k == key) {
            let mut shown = String::new();
            write_json_string(&key, &mut shown);
            slot.1 = value;
            self.record("duplicate_keys", key_byte, format!("kept the last value for duplicate key {shown}"));
        } else {
            entries.push((key, value));
        }
    }

    fn parse_key(&mut self) -> Option<String> {
        match self.peek_char()? {
            '"' | '\'' | '\u{201C}' | '\u{2018}' => Some(self.parse_string()),
            c if c.is_alphabetic() || c == '_' || c == '$' => {
                let start = self.pos;
                let key = self.read_ident();
                self.record("unquoted_keys", start, format!("quoted unquoted key '{key}'"));
                Some(key)
            }
            _ => None,
        }
    }

    fn read_ident(&mut self) -> String {
        let start = self.pos;
        while let Some(c) = self.peek_char() {
            if c.is_alphanumeric() || c == '_' || c == '$' {
                self.pos += c.len_utf8();
            } else {
                break;
            }
        }
        self.text[start..self.pos].to_string()
    }

    fn read_word(&mut self) -> String {
        let start = self.pos;
        while self.peek_char().is_some_and(|c| c.is_ascii_alphabetic()) {
            self.pos += 1;
        }
        self.text[start..self.pos].to_string()
    }

    fn parse_keyword(&mut self) -> Option<Value> {
        let start = self.pos;
        let word = self.read_word();
        match word.as_str() {
            "true" => Some(Value::Bool(true)),
            "false" => Some(Value::Bool(false)),
            "null" => Some(Value::Null),
            "True" => {
                self.record("python_literals", start, "replaced Python literal True with true");
                Some(Value::Bool(true))
            }
            "False" => {
                self.record("python_literals", start, "replaced Python literal False with false");
                Some(Value::Bool(false))
            }
            "None" => {
                self.record("python_literals", start, "replaced Python literal None with null");
                Some(Value::Null)
            }
            w if w.eq_ignore_ascii_case("nan") => {
                self.record("nan_infinity", start, "replaced NaN with null");
                Some(Value::Null)
            }
            w if w.eq_ignore_ascii_case("infinity") || w.eq_ignore_ascii_case("inf") => {
                self.record("nan_infinity", start, "replaced Infinity with null");
                Some(Value::Null)
            }
            _ => {
                self.pos = start; // not a keyword; leave the text untouched
                None
            }
        }
    }

    fn parse_string(&mut self) -> String {
        let open_byte = self.pos;
        let open = self.peek_char().unwrap_or('"');
        let close = match open {
            '\u{201C}' => '\u{201D}',
            '\u{2018}' => '\u{2019}',
            c => c,
        };
        match open {
            '"' => {}
            '\'' => self.record("single_quotes", open_byte, "converted single-quoted string to double quotes"),
            _ => self.record("smart_quotes", open_byte, "converted smart quotes to double quotes"),
        }
        self.pos += open.len_utf8(); // opening quote
        let mut out = String::new();
        loop {
            match self.peek_char() {
                None => {
                    self.incomplete = true; // unterminated string
                    return out;
                }
                Some('\\') => self.parse_escape(&mut out, close),
                Some(c) if c == close => {
                    self.pos += c.len_utf8();
                    return out;
                }
                Some(c) => {
                    if (c as u32) < 0x20 {
                        self.record(
                            "control_chars",
                            self.pos,
                            format!("escaped literal control character U+{:04X} in string", c as u32),
                        );
                    }
                    out.push(c);
                    self.pos += c.len_utf8();
                }
            }
        }
    }

    fn parse_escape(&mut self, out: &mut String, close: char) {
        self.pos += 1; // backslash
        let Some(c) = self.peek_char() else {
            self.incomplete = true;
            return;
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
                return;
            }
            other if other == close => close,
            other => {
                // Unknown escape: keep the character literally (lenient).
                out.push(other);
                self.pos += other.len_utf8();
                return;
            }
        };
        out.push(mapped);
        self.pos += 1; // the escaped char is ASCII here
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

    fn parse_number(&mut self) -> Option<Value> {
        let start = self.pos;
        let neg = self.peek() == Some(b'-');
        if neg {
            self.bump();
        }
        if matches!(self.peek(), Some(b'I' | b'i')) {
            let word = self.read_word();
            if word.eq_ignore_ascii_case("infinity") || word.eq_ignore_ascii_case("inf") {
                self.record("nan_infinity", start, "replaced Infinity with null");
                return Some(Value::Null);
            }
            self.pos = start;
            return None;
        }
        let body_start = self.pos;
        while matches!(self.peek(), Some(b'0'..=b'9' | b'.' | b'e' | b'E' | b'+' | b'-')) {
            self.bump();
        }
        if self.pos == body_start {
            self.pos = start; // a lone '-'
            return None;
        }
        let body = self.text[body_start..self.pos].to_string();
        self.interpret_number(neg, &body, start)
    }

    fn interpret_number(&mut self, neg: bool, body: &str, start: usize) -> Option<Value> {
        if !body.as_bytes().first().is_some_and(u8::is_ascii_digit) {
            return None;
        }
        let int_end = body.find(['.', 'e', 'E']).unwrap_or(body.len());
        let int_part = &body[..int_end];
        let rest = &body[int_end..];
        let cleaned_int = if int_part.len() > 1 && int_part.starts_with('0') {
            let trimmed = int_part.trim_start_matches('0');
            let cleaned = if trimmed.is_empty() { "0" } else { trimmed };
            self.record("leading_zeros", start, format!("stripped leading zeros from '{int_part}'"));
            cleaned
        } else {
            int_part
        };
        let lexeme = format!("{}{}{}", if neg { "-" } else { "" }, cleaned_int, rest);
        if rest.is_empty() {
            match lexeme.parse::<i64>() {
                Ok(i) => Some(Value::Int(i)),
                Err(_) if lexeme.trim_start_matches('-').bytes().all(|b| b.is_ascii_digit()) => {
                    Some(Value::BigInt(lexeme))
                }
                Err(_) => None,
            }
        } else {
            match lexeme.parse::<f64>() {
                Ok(f) if f.is_finite() => Some(Value::Float(f)),
                _ => None,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rep(text: &str) -> Repaired {
        repair(text).unwrap()
    }

    fn kinds(text: &str) -> Vec<&'static str> {
        rep(text).repairs.into_iter().map(|r| r.kind).collect()
    }

    #[test]
    fn clean_json_is_unchanged_and_unrepaired() {
        let r = rep(r#"{"a": 1, "b": [true, null, "x"], "n": -2.5e3}"#);
        assert!(r.repairs.is_empty());
        assert!(!r.incomplete);
        assert_eq!(r.value.to_json(), r#"{"a": 1, "b": [true, null, "x"], "n": -2500.0}"#);
    }

    #[test]
    fn trailing_comma() {
        assert_eq!(kinds(r#"{"a": 1, "b": 2,}"#), vec!["trailing_comma"]);
        assert_eq!(kinds("[1, 2, 3, ]"), vec!["trailing_comma"]);
        assert_eq!(rep(r#"{"a": 1,}"#).value.to_json(), r#"{"a": 1}"#);
    }

    #[test]
    fn single_and_smart_quotes() {
        let r = rep("{'intent': 'cancel'}");
        assert_eq!(r.repairs.iter().filter(|x| x.kind == "single_quotes").count(), 2);
        assert_eq!(r.value.to_json(), r#"{"intent": "cancel"}"#);
        let s = rep("{\u{201C}k\u{201D}: \u{2018}v\u{2019}}");
        assert!(s.repairs.iter().all(|x| x.kind == "smart_quotes" || x.kind == "unquoted_keys"));
        assert_eq!(s.value.to_json(), r#"{"k": "v"}"#);
    }

    #[test]
    fn unquoted_keys() {
        let r = rep("{intent: 1, score: 2}");
        assert_eq!(r.repairs.iter().filter(|x| x.kind == "unquoted_keys").count(), 2);
        assert_eq!(r.value.to_json(), r#"{"intent": 1, "score": 2}"#);
    }

    #[test]
    fn python_literals() {
        let r = rep(r#"{"ok": True, "no": False, "v": None}"#);
        assert_eq!(r.repairs.iter().filter(|x| x.kind == "python_literals").count(), 3);
        assert_eq!(r.value.to_json(), r#"{"ok": true, "no": false, "v": null}"#);
    }

    #[test]
    fn comments() {
        let r = rep("{\n  // the intent\n  \"a\": 1 /* inline */\n}");
        assert_eq!(r.repairs.iter().filter(|x| x.kind == "comment").count(), 2);
        assert_eq!(r.value.to_json(), r#"{"a": 1}"#);
    }

    #[test]
    fn nan_and_infinity_become_null() {
        assert_eq!(rep(r#"{"a": NaN, "b": Infinity, "c": -Infinity}"#).value.to_json(), r#"{"a": null, "b": null, "c": null}"#);
        assert_eq!(kinds(r#"[NaN, Infinity, -Infinity]"#), vec!["nan_infinity", "nan_infinity", "nan_infinity"]);
    }

    #[test]
    fn bom_is_stripped() {
        let r = rep("\u{FEFF}{\"a\": 1}");
        assert_eq!(r.repairs.first().map(|x| x.kind), Some("bom"));
        assert_eq!(r.value.to_json(), r#"{"a": 1}"#);
    }

    #[test]
    fn duplicate_keys_keep_last() {
        let r = rep(r#"{"a": 1, "a": 2, "a": 3}"#);
        assert_eq!(r.repairs.iter().filter(|x| x.kind == "duplicate_keys").count(), 2);
        assert_eq!(r.value.to_json(), r#"{"a": 3}"#);
    }

    #[test]
    fn leading_zeros() {
        let r = rep("[007, -042, 0, 0.5]");
        assert_eq!(r.repairs.iter().filter(|x| x.kind == "leading_zeros").count(), 2);
        assert_eq!(r.value.to_json(), "[7, -42, 0, 0.5]");
    }

    #[test]
    fn big_integers_are_preserved_without_repair() {
        let r = rep("[123456789012345678901234567890]");
        assert!(r.repairs.is_empty());
        assert_eq!(r.value.to_json(), "[123456789012345678901234567890]");
    }

    #[test]
    fn control_characters_in_strings() {
        let r = rep("{\"a\": \"line1\nline2\"}");
        assert_eq!(r.repairs.iter().filter(|x| x.kind == "control_chars").count(), 1);
        assert_eq!(r.value, Value::Object(vec![("a".into(), Value::Str("line1\nline2".into()))]));
    }

    #[test]
    fn truncated_object_closes_and_marks_incomplete() {
        let r = rep(r#"{"a": 1, "b": {"c": 2"#);
        assert!(r.incomplete);
        let last = r.repairs.last().unwrap();
        assert_eq!(last.kind, "truncated");
        assert!(last.detail.contains("} }"), "{}", last.detail);
        assert_eq!(r.value.to_json(), r#"{"a": 1, "b": {"c": 2}}"#);
    }

    #[test]
    fn truncated_array_and_dangling_key() {
        let r = rep(r#"[1, 2, 3"#);
        assert!(r.incomplete);
        assert_eq!(r.value.to_json(), "[1, 2, 3]");
        // A key with no value is dropped, and the object is closed.
        let d = rep(r#"{"a": 1, "b":"#);
        assert!(d.incomplete);
        assert_eq!(d.value.to_json(), r#"{"a": 1}"#);
    }

    #[test]
    fn truncated_string() {
        let r = rep(r#"{"a": "unterminated"#);
        assert!(r.incomplete);
        assert_eq!(r.value.to_json(), r#"{"a": "unterminated"}"#);
    }

    #[test]
    fn no_json_is_an_error() {
        assert_eq!(repair("").unwrap_err().code, "json.not_found");
        assert_eq!(repair("   \n  ").unwrap_err().code, "json.not_found");
        assert_eq!(repair("just some prose").unwrap_err().code, "json.not_found");
    }

    #[test]
    fn repair_offsets_are_code_points() {
        // The smart quote before the comma is multi-byte; `at` must be a code
        // point offset, not a byte offset.
        let r = rep("{\"é\": 1,}");
        let tc = r.repairs.iter().find(|x| x.kind == "trailing_comma").unwrap();
        assert_eq!(tc.at, 7); // { " é " :  space 1 , -> comma at code point 7
    }
}
