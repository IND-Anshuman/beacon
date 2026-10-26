//! A strict RFC 8259 JSON parser.
//!
//! beacon owns its parser (rather than delegating to `serde_json`) because the
//! error codes and messages it produces are part of the public contract and
//! must not change when a dependency is upgraded. It also:
//!
//! * reports byte offsets that callers convert to code-point positions,
//! * keeps integers of any size exact,
//! * rejects duplicate object keys instead of silently picking one,
//! * enforces a fixed nesting limit, so hostile input cannot overflow the
//!   stack of the Python process.
//!
//! Nothing is repaired: trailing commas, comments, single quotes, `NaN`,
//! unescaped control characters and lone surrogates are all errors.

use crate::error::describe_char;
use crate::value::Value;

/// Maximum nesting depth of arrays and objects.
pub const MAX_DEPTH: usize = 512;

/// A parse error at a byte offset of the input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JsonError {
    pub code: &'static str,
    pub message: String,
    pub byte: usize,
}

type PResult<T> = Result<T, JsonError>;

/// Parses a complete JSON document. Leading and trailing JSON whitespace is
/// allowed; anything else after the value is an error.
pub fn parse_document(text: &str) -> PResult<Value> {
    let mut p = Parser::new(text, 0);
    p.skip_ws();
    let value = p.parse_value(0)?;
    p.skip_ws();
    if p.pos < p.bytes.len() {
        return Err(
            p.err_here("json.trailing_characters", format!("unexpected {} after JSON value", p.describe_current()))
        );
    }
    Ok(value)
}

/// Parses one JSON value starting exactly at byte `start` (no leading
/// whitespace is skipped). Returns the value and the byte offset just past it.
pub fn parse_value_at(text: &str, start: usize) -> PResult<(Value, usize)> {
    let mut p = Parser::new(text, start);
    let value = p.parse_value(0)?;
    Ok((value, p.pos))
}

/// JSON insignificant whitespace.
pub fn is_json_ws(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | b'\r')
}

struct Parser<'a> {
    text: &'a str,
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn new(text: &'a str, start: usize) -> Self {
        Parser { text, bytes: text.as_bytes(), pos: start.min(text.len()) }
    }

    fn err(&self, code: &'static str, message: impl Into<String>, byte: usize) -> JsonError {
        JsonError { code, message: message.into(), byte }
    }

    fn err_here(&self, code: &'static str, message: impl Into<String>) -> JsonError {
        self.err(code, message, self.pos)
    }

    fn eof(&self) -> JsonError {
        self.err_here("json.unexpected_end", "unexpected end of input")
    }

    fn current_char(&self) -> Option<char> {
        self.text.get(self.pos..).and_then(|s| s.chars().next())
    }

    fn describe_current(&self) -> String {
        match self.current_char() {
            Some(c) => describe_char(c),
            None => "end of input".to_string(),
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn skip_ws(&mut self) {
        while let Some(b) = self.peek() {
            if is_json_ws(b) {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn parse_value(&mut self, depth: usize) -> PResult<Value> {
        let Some(b) = self.peek() else {
            return Err(self.eof());
        };
        match b {
            b'{' => self.parse_object(depth + 1),
            b'[' => self.parse_array(depth + 1),
            b'"' => Ok(Value::Str(self.parse_string()?)),
            b't' => self.parse_literal("true", Value::Bool(true)),
            b'f' => self.parse_literal("false", Value::Bool(false)),
            b'n' => self.parse_literal("null", Value::Null),
            b'-' | b'0'..=b'9' => self.parse_number(),
            _ => Err(self
                .err_here("json.expected_value", format!("expected a JSON value, found {}", self.describe_current()))),
        }
    }

    fn check_depth(&self, depth: usize) -> PResult<()> {
        if depth > MAX_DEPTH {
            Err(self.err_here("json.too_deep", format!("JSON nesting is deeper than {MAX_DEPTH} levels")))
        } else {
            Ok(())
        }
    }

    fn parse_literal(&mut self, word: &'static str, value: Value) -> PResult<Value> {
        let end = self.pos + word.len();
        if self.bytes.get(self.pos..end) == Some(word.as_bytes()) {
            self.pos = end;
            Ok(value)
        } else {
            let available = &self.bytes[self.pos..];
            if word.as_bytes().starts_with(available) {
                // A prefix of the literal followed by end of input: truncated.
                self.pos = self.bytes.len();
                return Err(self.eof());
            }
            Err(self.err_here("json.invalid_literal", format!("invalid literal, expected '{word}'")))
        }
    }

    fn parse_object(&mut self, depth: usize) -> PResult<Value> {
        self.check_depth(depth)?;
        self.pos += 1; // '{'
        let mut entries: Vec<(String, Value)> = Vec::new();
        self.skip_ws();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(Value::Object(entries));
        }
        loop {
            self.skip_ws();
            match self.peek() {
                None => return Err(self.eof()),
                Some(b'"') => {}
                Some(b'}') if !entries.is_empty() => {
                    return Err(self.err_here("json.trailing_comma", "trailing comma before '}'"));
                }
                Some(_) => {
                    return Err(self.err_here(
                        "json.expected_key",
                        format!("expected a double-quoted object key, found {}", self.describe_current()),
                    ));
                }
            }
            let key_start = self.pos;
            let key = self.parse_string()?;
            if entries.iter().any(|(k, _)| *k == key) {
                let mut shown = String::new();
                crate::value::write_json_string(&key, &mut shown);
                return Err(self.err("json.duplicate_key", format!("duplicate object key {shown}"), key_start));
            }
            self.skip_ws();
            match self.peek() {
                None => return Err(self.eof()),
                Some(b':') => self.pos += 1,
                Some(_) => {
                    return Err(self.err_here(
                        "json.expected_colon",
                        format!("expected ':' after object key, found {}", self.describe_current()),
                    ));
                }
            }
            self.skip_ws();
            let value = self.parse_value(depth)?;
            entries.push((key, value));
            self.skip_ws();
            match self.peek() {
                None => return Err(self.eof()),
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(Value::Object(entries));
                }
                Some(_) => {
                    return Err(self.err_here(
                        "json.expected_comma",
                        format!("expected ',' or '}}' after object value, found {}", self.describe_current()),
                    ));
                }
            }
        }
    }

    fn parse_array(&mut self, depth: usize) -> PResult<Value> {
        self.check_depth(depth)?;
        self.pos += 1; // '['
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(Value::Array(items));
        }
        loop {
            self.skip_ws();
            match self.peek() {
                None => return Err(self.eof()),
                Some(b']') if !items.is_empty() => {
                    return Err(self.err_here("json.trailing_comma", "trailing comma before ']'"));
                }
                Some(_) => {}
            }
            items.push(self.parse_value(depth)?);
            self.skip_ws();
            match self.peek() {
                None => return Err(self.eof()),
                Some(b',') => self.pos += 1,
                Some(b']') => {
                    self.pos += 1;
                    return Ok(Value::Array(items));
                }
                Some(_) => {
                    return Err(self.err_here(
                        "json.expected_comma",
                        format!("expected ',' or ']' after array item, found {}", self.describe_current()),
                    ));
                }
            }
        }
    }

    fn parse_string(&mut self) -> PResult<String> {
        let open = self.pos;
        self.pos += 1; // opening quote
        let mut out = String::new();
        loop {
            // Copy the longest run of plain characters in one go.
            let run_start = self.pos;
            while let Some(b) = self.peek() {
                if b == b'"' || b == b'\\' || b < 0x20 {
                    break;
                }
                self.pos += 1;
            }
            // Run boundaries are ASCII bytes, so this slice is on char boundaries.
            out.push_str(&self.text[run_start..self.pos]);
            match self.peek() {
                None => {
                    return Err(self.err("json.unterminated_string", "unterminated string", open));
                }
                Some(b'"') => {
                    self.pos += 1;
                    return Ok(out);
                }
                Some(b'\\') => self.parse_escape(&mut out)?,
                Some(b) => {
                    return Err(self.err_here(
                        "json.control_character",
                        format!("unescaped control character U+{:04X} in string", b),
                    ));
                }
            }
        }
    }

    fn parse_escape(&mut self, out: &mut String) -> PResult<()> {
        let esc_start = self.pos;
        self.pos += 1; // backslash
        let Some(b) = self.peek() else {
            return Err(self.err("json.unterminated_string", "unterminated string", esc_start));
        };
        self.pos += 1;
        let c = match b {
            b'"' => '"',
            b'\\' => '\\',
            b'/' => '/',
            b'b' => '\u{08}',
            b'f' => '\u{0C}',
            b'n' => '\n',
            b'r' => '\r',
            b't' => '\t',
            b'u' => return self.parse_unicode_escape(esc_start, out),
            _ => {
                self.pos = esc_start;
                let shown = self.text[esc_start + 1..].chars().next().map(describe_char).unwrap_or_default();
                return Err(self.err_here(
                    "json.invalid_escape",
                    format!("invalid escape sequence: backslash followed by {shown}"),
                ));
            }
        };
        out.push(c);
        Ok(())
    }

    fn read_hex4(&mut self, esc_start: usize) -> PResult<u32> {
        let end = self.pos + 4;
        let Some(digits) = self.bytes.get(self.pos..end) else {
            if self.bytes[self.pos..].iter().all(u8::is_ascii_hexdigit) {
                self.pos = self.bytes.len();
                return Err(self.err("json.unterminated_string", "unterminated string", esc_start));
            }
            return Err(self.err(
                "json.invalid_unicode_escape",
                "invalid \\u escape: expected 4 hex digits",
                esc_start,
            ));
        };
        let mut v = 0u32;
        for &d in digits {
            let n = match d {
                b'0'..=b'9' => d - b'0',
                b'a'..=b'f' => d - b'a' + 10,
                b'A'..=b'F' => d - b'A' + 10,
                _ => {
                    return Err(self.err(
                        "json.invalid_unicode_escape",
                        "invalid \\u escape: expected 4 hex digits",
                        esc_start,
                    ));
                }
            };
            v = v * 16 + u32::from(n);
        }
        self.pos = end;
        Ok(v)
    }

    fn parse_unicode_escape(&mut self, esc_start: usize, out: &mut String) -> PResult<()> {
        let first = self.read_hex4(esc_start)?;
        let code = if (0xD800..0xDC00).contains(&first) {
            // High surrogate: must be followed by \uDC00-\uDFFF.
            if self.bytes.get(self.pos..self.pos + 2) != Some(b"\\u") {
                return Err(self.err("json.lone_surrogate", "unpaired surrogate in \\u escape", esc_start));
            }
            let second_start = self.pos;
            self.pos += 2;
            let second = self.read_hex4(second_start)?;
            if !(0xDC00..0xE000).contains(&second) {
                return Err(self.err("json.lone_surrogate", "unpaired surrogate in \\u escape", esc_start));
            }
            0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)
        } else if (0xDC00..0xE000).contains(&first) {
            return Err(self.err("json.lone_surrogate", "unpaired surrogate in \\u escape", esc_start));
        } else {
            first
        };
        match char::from_u32(code) {
            Some(c) => {
                out.push(c);
                Ok(())
            }
            None => Err(self.err("json.invalid_unicode_escape", "invalid \\u escape", esc_start)),
        }
    }

    fn parse_number(&mut self) -> PResult<Value> {
        let start = self.pos;
        let invalid = |p: &Self, at: usize| p.err("json.invalid_number", "invalid number", at);
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        match self.peek() {
            None => return Err(self.eof()),
            Some(b'0') => {
                self.pos += 1;
                if matches!(self.peek(), Some(b'0'..=b'9')) {
                    return Err(invalid(self, start));
                }
            }
            Some(b'1'..=b'9') => self.skip_digits(),
            Some(_) => return Err(invalid(self, start)),
        }
        let mut is_float = false;
        if self.peek() == Some(b'.') {
            is_float = true;
            self.pos += 1;
            match self.peek() {
                None => return Err(self.eof()),
                Some(b'0'..=b'9') => self.skip_digits(),
                Some(_) => return Err(invalid(self, start)),
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            is_float = true;
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            match self.peek() {
                None => return Err(self.eof()),
                Some(b'0'..=b'9') => self.skip_digits(),
                Some(_) => return Err(invalid(self, start)),
            }
        }
        let lexeme = &self.text[start..self.pos];
        if is_float {
            match lexeme.parse::<f64>() {
                Ok(f) if f.is_finite() => Ok(Value::Float(f)),
                _ => Err(self.err("json.number_out_of_range", "number is out of range for a 64-bit float", start)),
            }
        } else {
            match lexeme.parse::<i64>() {
                Ok(i) => Ok(Value::Int(i)),
                // Valid JSON integer syntax that overflows i64: keep it exact.
                Err(_) => Ok(Value::BigInt(lexeme.to_string())),
            }
        }
    }

    fn skip_digits(&mut self) {
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn obj(pairs: Vec<(&str, Value)>) -> Value {
        Value::Object(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
    }

    #[test]
    fn parses_basic_document() {
        let v = parse_document(r#" {"b": [1, 2.5, -0, true, null], "a": "xé😀"} "#).unwrap();
        assert_eq!(
            v,
            obj(vec![
                (
                    "b",
                    Value::Array(vec![Value::Int(1), Value::Float(2.5), Value::Int(0), Value::Bool(true), Value::Null])
                ),
                ("a", Value::Str("xé😀".into())),
            ])
        );
    }

    #[test]
    fn big_integers_are_exact() {
        assert_eq!(
            parse_document("123456789012345678901234567890").unwrap(),
            Value::BigInt("123456789012345678901234567890".into())
        );
        assert_eq!(parse_document("-9223372036854775808").unwrap(), Value::Int(i64::MIN));
    }

    #[test]
    fn rejects_repairs() {
        let cases = [
            ("[1, 2,]", "json.trailing_comma"),
            (r#"{"a": 1,}"#, "json.trailing_comma"),
            ("{'a': 1}", "json.expected_key"),
            ("{a: 1}", "json.expected_key"),
            ("[NaN]", "json.expected_value"),
            ("[01]", "json.invalid_number"),
            ("[1.]", "json.invalid_number"),
            ("[tru]", "json.invalid_literal"),
            ("\"a\nb\"", "json.control_character"),
            (r#""\x""#, "json.invalid_escape"),
            (r#""\ud800""#, "json.lone_surrogate"),
            (r#""\udc00""#, "json.lone_surrogate"),
            (r#"{"a": 1, "a": 2}"#, "json.duplicate_key"),
            ("[1] x", "json.trailing_characters"),
            ("1e400", "json.number_out_of_range"),
            (r#"{"a" 1}"#, "json.expected_colon"),
            ("[1 2]", "json.expected_comma"),
        ];
        for (text, code) in cases {
            let err = parse_document(text).unwrap_err();
            assert_eq!(err.code, code, "input {text:?}: {err:?}");
        }
    }

    #[test]
    fn truncation_is_reported_as_end_of_input() {
        for text in [r#"{"a": [1, 2"#, r#"{"a": tr"#, r#"{"a": -"#, "[1.5e"] {
            let err = parse_document(text).unwrap_err();
            assert_eq!(err.code, "json.unexpected_end", "input {text:?}");
        }
        let err = parse_document(r#"{"a": "abc"#).unwrap_err();
        assert_eq!(err.code, "json.unterminated_string");
        assert_eq!(err.byte, 6);
    }

    #[test]
    fn depth_limit() {
        let deep = "[".repeat(MAX_DEPTH + 1) + &"]".repeat(MAX_DEPTH + 1);
        assert_eq!(parse_document(&deep).unwrap_err().code, "json.too_deep");
        let ok = "[".repeat(MAX_DEPTH) + &"]".repeat(MAX_DEPTH);
        assert!(parse_document(&ok).is_ok());
    }

    #[test]
    fn agrees_with_serde_json_on_valid_input() {
        let docs = [
            r#"{"a": {"b": [1, -2, 3.25e-3, "s\t\"q\""]}, "c": false}"#,
            "[0.1, 1e10, -1.5E+3, 123456789]",
            r#""\/\\\b\f\n\r\t""#,
        ];
        for doc in docs {
            let ours = parse_document(doc).unwrap();
            let theirs: serde_json::Value = serde_json::from_str(doc).unwrap();
            assert_eq!(ours.to_json(), to_value(&theirs).to_json());
        }
    }

    fn to_value(v: &serde_json::Value) -> Value {
        match v {
            serde_json::Value::Null => Value::Null,
            serde_json::Value::Bool(b) => Value::Bool(*b),
            serde_json::Value::Number(n) => match n.as_i64() {
                Some(i) => Value::Int(i),
                None => Value::Float(n.as_f64().unwrap_or(f64::NAN)),
            },
            serde_json::Value::String(s) => Value::Str(s.clone()),
            serde_json::Value::Array(a) => Value::Array(a.iter().map(to_value).collect()),
            serde_json::Value::Object(o) => Value::Object(o.iter().map(|(k, v)| (k.clone(), to_value(v))).collect()),
        }
    }
}
