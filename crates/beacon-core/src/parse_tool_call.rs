//! Extract tool / function calls from LLM output.
//!
//! Formats are tried in three tiers; the first tier that finds anything wins:
//!
//! 1. **Tagged** — explicit markers, in text order:
//!    * `hermes`: `<tool_call>{json}</tool_call>` (Hermes, Qwen, many fine-tunes)
//!    * `bracket`: `[TOOL_CALL]{json}[/TOOL_CALL]` or
//!      `[TOOL_CALL]name=search;args={json}[/TOOL_CALL]`
//!    * `mistral`: `[TOOL_CALLS][{json}, ...]` or `[TOOL_CALLS]name[ARGS]{json}`
//!    * `llama`: `<|python_tag|>{json}` or `<|python_tag|>tool.call(k=v)`
//!    * `xml_invoke`: `<invoke name="x"><parameter name="k">v</parameter></invoke>`
//! 2. **JSON** (`json`) — JSON objects/arrays found the way `extract_json`
//!    finds them, kept only if they have a tool-call shape:
//!    `{"name", "arguments"|"parameters"|"input"|"args"}`,
//!    `{"type": "tool_use", "name", "input"}`, `{"function": {...}}`,
//!    `{"tool_calls": [...]}`, `{"function_call": {...}}` or an array of calls.
//!    `arguments` given as a JSON string (OpenAI) is parsed strictly.
//! 3. **Python call** (`python`) — `name(key=value, ...)` with Python or JSON
//!    literals. Only keyword arguments are supported.
//!
//! Inside a tier, malformed input that clearly intended a call raises
//! `MalformedOutputError` with its position — it is never skipped.

use crate::error::{BlockError, ErrorKind, describe_char};
use crate::extract_json::{find_fences, json_like_opener};
use crate::json::{self, is_json_ws};
use crate::value::Value;

pub type Arguments = Vec<(String, Value)>;

#[derive(Debug, Clone, PartialEq)]
pub struct ToolCall {
    pub name: String,
    pub arguments: Arguments,
    pub format: &'static str,
}

const MAX_DEPTH: usize = 128;

fn malformed(code: &'static str, message: impl Into<String>, text: &str, byte: usize) -> BlockError {
    BlockError::at(ErrorKind::Malformed, code, message, text, byte)
}

fn json_err(text: &str, e: &json::JsonError, base: usize) -> BlockError {
    malformed(e.code, e.message.clone(), text, base + e.byte)
}

// ------------------------------------------------------------------ shapes

const ARG_KEYS: [&str; 4] = ["arguments", "parameters", "input", "args"];
const META_KEYS: [&str; 4] = ["id", "type", "call_id", "index"];

/// A shape error: `(code, message)`.
type ShapeError = (&'static str, String);
type ShapeResult = Option<Result<Vec<(String, Arguments)>, ShapeError>>;

fn arguments_from(v: &Value) -> Result<Arguments, ShapeError> {
    match v {
        Value::Object(entries) => Ok(entries.clone()),
        Value::Str(s) => match json::parse_document(s) {
            Ok(Value::Object(entries)) => Ok(entries),
            Ok(other) => Err((
                "tool_call.invalid_arguments",
                format!("tool call arguments must be a JSON object, got {}", other.type_name()),
            )),
            Err(e) => Err((
                "tool_call.invalid_arguments",
                format!("tool call arguments string is not valid JSON ({})", e.message),
            )),
        },
        other => Err((
            "tool_call.invalid_arguments",
            format!("tool call arguments must be a JSON object, got {}", other.type_name()),
        )),
    }
}

fn name_from(v: Option<&Value>) -> Result<String, ShapeError> {
    match v {
        Some(Value::Str(s)) if !s.trim().is_empty() => Ok(s.clone()),
        _ => Err(("tool_call.invalid_name", "tool call name must be a non-empty string".to_string())),
    }
}

/// `None` if the object does not look like a tool call at all.
fn call_from_object(v: &Value) -> Option<Result<(String, Arguments), ShapeError>> {
    let Value::Object(entries) = v else { return None };
    let has = |k: &str| v.get(k).is_some();

    if let Some(f @ Value::Object(_)) = v.get("function") {
        if f.get("name").is_some() && entries.iter().all(|(k, _)| k == "function" || META_KEYS.contains(&k.as_str())) {
            return call_from_object(f);
        }
    }
    if v.get("type").and_then(Value::as_str) == Some("tool_use") && has("name") {
        return Some(name_from(v.get("name")).and_then(|name| {
            let args = match v.get("input") {
                Some(a) => arguments_from(a)?,
                None => Vec::new(),
            };
            Ok((name, args))
        }));
    }
    if !has("name") {
        return None;
    }
    let arg_keys: Vec<&str> = ARG_KEYS.iter().copied().filter(|k| has(k)).collect();
    let only_known =
        entries.iter().all(|(k, _)| k == "name" || ARG_KEYS.contains(&k.as_str()) || META_KEYS.contains(&k.as_str()));
    if arg_keys.is_empty() || !only_known {
        return None;
    }
    if arg_keys.len() > 1 {
        return Some(Err((
            "tool_call.ambiguous_arguments",
            format!("tool call has more than one arguments key: {}", arg_keys.join(", ")),
        )));
    }
    Some(name_from(v.get("name")).and_then(|name| {
        let args = v.get(arg_keys[0]).map(arguments_from).transpose()?.unwrap_or_default();
        Ok((name, args))
    }))
}

fn calls_from_value(v: &Value) -> ShapeResult {
    match v {
        Value::Object(_) => {
            if let Some(Value::Array(items)) = v.get("tool_calls") {
                let mut out = Vec::new();
                for (i, item) in items.iter().enumerate() {
                    match call_from_object(item) {
                        Some(Ok(c)) => out.push(c),
                        Some(Err(e)) => return Some(Err(e)),
                        None => {
                            return Some(Err((
                                "tool_call.unrecognized",
                                format!("item {i} of \"tool_calls\" is not a tool call"),
                            )));
                        }
                    }
                }
                return Some(Ok(out));
            }
            if let Some(f @ Value::Object(_)) = v.get("function_call") {
                return Some(match call_from_object(f) {
                    Some(r) => r.map(|c| vec![c]),
                    None => Err(("tool_call.unrecognized", "\"function_call\" is not a tool call".to_string())),
                });
            }
            call_from_object(v).map(|r| r.map(|c| vec![c]))
        }
        Value::Array(items) if !items.is_empty() => {
            let mut out = Vec::new();
            for item in items {
                match call_from_object(item)? {
                    Ok(c) => out.push(c),
                    Err(e) => return Some(Err(e)),
                }
            }
            Some(Ok(out))
        }
        _ => None,
    }
}

fn to_calls(found: Vec<(String, Arguments)>, format: &'static str) -> Vec<ToolCall> {
    found.into_iter().map(|(name, arguments)| ToolCall { name, arguments, format }).collect()
}

/// Parses `content` (at byte `base` of `text`) as a JSON document that must be
/// a tool call (or list of calls).
fn tagged_json(text: &str, content: &str, base: usize, format: &'static str) -> Result<Vec<ToolCall>, BlockError> {
    let lead = content.len() - content.trim_start().len();
    let trimmed = content.trim();
    let value = json::parse_document(trimmed).map_err(|e| json_err(text, &e, base + lead))?;
    match calls_from_value(&value) {
        Some(Ok(calls)) => Ok(to_calls(calls, format)),
        Some(Err((code, msg))) => Err(malformed(code, msg, text, base + lead)),
        None => {
            Err(malformed("tool_call.unrecognized", "tagged content is not a recognized tool call", text, base + lead))
        }
    }
}

// ------------------------------------------------------------------ python literals

struct PyParser<'a> {
    text: &'a str,
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> PyParser<'a> {
    fn new(text: &'a str, pos: usize) -> Self {
        PyParser { text, bytes: text.as_bytes(), pos }
    }

    fn err(&self, code: &'static str, message: impl Into<String>) -> BlockError {
        malformed(code, message, self.text, self.pos)
    }

    fn found(&self) -> String {
        self.text[self.pos..].chars().next().map_or("end of input".to_string(), describe_char)
    }

    fn ws(&mut self) {
        while self.pos < self.bytes.len() && (self.bytes[self.pos] as char).is_ascii_whitespace() {
            self.pos += 1;
        }
    }

    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn ident(&mut self) -> Option<&'a str> {
        let start = self.pos;
        match self.peek() {
            Some(b) if b.is_ascii_alphabetic() || b == b'_' => self.pos += 1,
            _ => return None,
        }
        while matches!(self.peek(), Some(b) if b.is_ascii_alphanumeric() || b == b'_') {
            self.pos += 1;
        }
        Some(&self.text[start..self.pos])
    }

    fn value(&mut self, depth: usize) -> Result<Value, BlockError> {
        if depth > MAX_DEPTH {
            return Err(self.err("tool_call.too_deep", format!("argument nesting is deeper than {MAX_DEPTH} levels")));
        }
        match self.peek() {
            None => Err(self.err("tool_call.unexpected_end", "unexpected end of input")),
            Some(b'"' | b'\'') => self.string().map(Value::Str),
            Some(b'-' | b'0'..=b'9') => match json::parse_value_at(self.text, self.pos) {
                Ok((v, end)) => {
                    self.pos = end;
                    Ok(v)
                }
                Err(e) => Err(json_err(self.text, &e, 0)),
            },
            Some(b'[') => self.sequence(b']', depth).map(Value::Array),
            Some(b'(') => self.sequence(b')', depth).map(Value::Array),
            Some(b'{') => self.dict(depth),
            Some(_) => {
                let start = self.pos;
                match self.ident() {
                    Some("True" | "true") => Ok(Value::Bool(true)),
                    Some("False" | "false") => Ok(Value::Bool(false)),
                    Some("None" | "null") => Ok(Value::Null),
                    _ => {
                        self.pos = start;
                        Err(self.err(
                            "tool_call.expected_value",
                            format!("expected a literal value, found {}", self.found()),
                        ))
                    }
                }
            }
        }
    }

    fn string(&mut self) -> Result<String, BlockError> {
        let open = self.pos;
        let quote = self.bytes[self.pos];
        self.pos += 1;
        let mut out = String::new();
        loop {
            let Some(c) = self.text[self.pos..].chars().next() else {
                self.pos = open;
                return Err(self.err("tool_call.unterminated_string", "unterminated string"));
            };
            match c {
                '\n' | '\r' => {
                    self.pos = open;
                    return Err(self.err("tool_call.unterminated_string", "unterminated string"));
                }
                '\\' => {
                    let esc = self.pos;
                    self.pos += 1;
                    let Some(e) = self.text[self.pos..].chars().next() else {
                        self.pos = open;
                        return Err(self.err("tool_call.unterminated_string", "unterminated string"));
                    };
                    self.pos += e.len_utf8();
                    let decoded = match e {
                        '\\' => Some('\\'),
                        '\'' => Some('\''),
                        '"' => Some('"'),
                        'n' => Some('\n'),
                        't' => Some('\t'),
                        'r' => Some('\r'),
                        '0' => Some('\0'),
                        'u' | 'x' => {
                            let n = if e == 'u' { 4 } else { 2 };
                            let hex = self.text.get(self.pos..self.pos + n);
                            let code = hex.and_then(|h| u32::from_str_radix(h, 16).ok());
                            self.pos += n;
                            code.and_then(char::from_u32)
                        }
                        _ => None,
                    };
                    match decoded {
                        Some(d) => out.push(d),
                        None => {
                            self.pos = esc;
                            return Err(self.err("tool_call.invalid_escape", "invalid escape sequence in string"));
                        }
                    }
                }
                c if c as u32 == u32::from(quote) => {
                    self.pos += 1;
                    return Ok(out);
                }
                c => {
                    out.push(c);
                    self.pos += c.len_utf8();
                }
            }
        }
    }

    fn sequence(&mut self, close: u8, depth: usize) -> Result<Vec<Value>, BlockError> {
        self.pos += 1;
        let mut items = Vec::new();
        loop {
            self.ws();
            if self.peek() == Some(close) {
                self.pos += 1;
                return Ok(items);
            }
            items.push(self.value(depth + 1)?);
            self.ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b) if b == close => {
                    self.pos += 1;
                    return Ok(items);
                }
                _ => {
                    return Err(self.err(
                        "tool_call.expected_comma",
                        format!("expected ',' or '{}', found {}", close as char, self.found()),
                    ));
                }
            }
        }
    }

    fn dict(&mut self, depth: usize) -> Result<Value, BlockError> {
        self.pos += 1;
        let mut entries: Arguments = Vec::new();
        loop {
            self.ws();
            match self.peek() {
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(Value::Object(entries));
                }
                Some(b'"' | b'\'') => {}
                _ => {
                    return Err(self.err(
                        "tool_call.expected_key",
                        format!("expected a quoted dictionary key, found {}", self.found()),
                    ));
                }
            }
            let key_pos = self.pos;
            let key = self.string()?;
            if entries.iter().any(|(k, _)| *k == key) {
                self.pos = key_pos;
                return Err(self.err("tool_call.duplicate_key", format!("duplicate dictionary key {key:?}")));
            }
            self.ws();
            if self.peek() != Some(b':') {
                return Err(self.err("tool_call.expected_colon", format!("expected ':', found {}", self.found())));
            }
            self.pos += 1;
            self.ws();
            let v = self.value(depth + 1)?;
            entries.push((key, v));
            self.ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(Value::Object(entries));
                }
                _ => {
                    return Err(
                        self.err("tool_call.expected_comma", format!("expected ',' or '}}', found {}", self.found()))
                    );
                }
            }
        }
    }

    /// Parses `(key=value, ...)` starting at `(`. Returns the arguments.
    fn call_arguments(&mut self) -> Result<Arguments, BlockError> {
        self.pos += 1; // '('
        let mut args: Arguments = Vec::new();
        loop {
            self.ws();
            if self.peek() == Some(b')') {
                self.pos += 1;
                return Ok(args);
            }
            let arg_start = self.pos;
            let name = self.ident();
            self.ws();
            let is_kw = name.is_some() && self.peek() == Some(b'=') && self.bytes.get(self.pos + 1) != Some(&b'=');
            let Some(name) = name.filter(|_| is_kw) else {
                self.pos = arg_start;
                return Err(
                    self.err("tool_call.positional_argument", "positional arguments are not supported; use name=value")
                );
            };
            if args.iter().any(|(k, _)| k == name) {
                self.pos = arg_start;
                return Err(self.err("tool_call.duplicate_argument", format!("duplicate argument '{name}'")));
            }
            self.pos += 1; // '='
            self.ws();
            let v = self.value(1)?;
            args.push((name.to_string(), v));
            self.ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b')') => {
                    self.pos += 1;
                    return Ok(args);
                }
                _ => {
                    return Err(self.err(
                        "tool_call.expected_comma",
                        format!("expected ',' or ')' after argument, found {}", self.found()),
                    ));
                }
            }
        }
    }
}

/// Reads a (possibly dotted) identifier ending at `(` at `pos`. Returns the
/// name and the byte offset of `(`.
fn call_head(text: &str, pos: usize) -> Option<(&str, usize)> {
    let bytes = text.as_bytes();
    let mut i = pos;
    loop {
        match bytes.get(i) {
            Some(b) if b.is_ascii_alphabetic() || *b == b'_' => i += 1,
            _ => return None,
        }
        while matches!(bytes.get(i), Some(b) if b.is_ascii_alphanumeric() || *b == b'_') {
            i += 1;
        }
        match bytes.get(i) {
            Some(b'.') => i += 1,
            Some(b'(') => return Some((&text[pos..i], i)),
            _ => return None,
        }
    }
}

/// Whether the parenthesised content at `paren` starts like keyword args.
fn call_like(text: &str, paren: usize) -> bool {
    let mut p = PyParser::new(text, paren + 1);
    p.ws();
    if p.peek() == Some(b')') {
        return true;
    }
    if p.ident().is_none() {
        return false;
    }
    p.ws();
    p.peek() == Some(b'=') && p.bytes.get(p.pos + 1) != Some(&b'=')
}

fn python_call_at(text: &str, pos: usize, format: &'static str) -> Option<Result<(ToolCall, usize), BlockError>> {
    let (name, paren) = call_head(text, pos)?;
    if !call_like(text, paren) {
        return None;
    }
    let mut p = PyParser::new(text, paren);
    Some(p.call_arguments().map(|arguments| (ToolCall { name: name.to_string(), arguments, format }, p.pos)))
}

fn scan_python(text: &str) -> Result<Vec<ToolCall>, BlockError> {
    let bytes = text.as_bytes();
    let mut calls = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        let b = bytes[i];
        let starts_ident = (b.is_ascii_alphabetic() || b == b'_')
            && (i == 0 || !(bytes[i - 1].is_ascii_alphanumeric() || bytes[i - 1] == b'_' || bytes[i - 1] == b'.'));
        if starts_ident {
            match python_call_at(text, i, "python") {
                Some(Ok((call, end))) => {
                    calls.push(call);
                    i = end;
                    continue;
                }
                Some(Err(e)) => return Err(e),
                None => {}
            }
        }
        i += 1;
    }
    Ok(calls)
}

// ------------------------------------------------------------------ tagged formats

struct Tagged {
    start: usize,
    result: Result<Vec<ToolCall>, BlockError>,
}

/// Finds `open ... close` blocks (an unclosed block runs to the end).
fn blocks<'t>(text: &'t str, open: &str, closes: &[&str]) -> Vec<(usize, usize, &'t str)> {
    let mut out = Vec::new();
    let mut from = 0;
    while let Some(rel) = text[from..].find(open) {
        let start = from + rel;
        let content_start = start + open.len();
        let (content_end, next) = closes
            .iter()
            .filter_map(|c| text[content_start..].find(c).map(|r| (content_start + r, content_start + r + c.len())))
            .min()
            .unwrap_or((text.len(), text.len()));
        out.push((start, content_start, &text[content_start..content_end]));
        from = next.max(content_start);
    }
    out
}

fn parse_bracket(text: &str, content: &str, base: usize) -> Result<Vec<ToolCall>, BlockError> {
    let trimmed = content.trim_start();
    if trimmed.starts_with('{') || trimmed.starts_with('[') {
        return tagged_json(text, content, base, "bracket");
    }
    // name=search;args={...}
    let lead = content.len() - trimmed.len();
    let bad = |at: usize| {
        malformed(
            "tool_call.unrecognized",
            "expected 'name=<tool>;args=<json object>' inside [TOOL_CALL]",
            text,
            base + at,
        )
    };
    let Some(rest) = trimmed.strip_prefix("name=") else { return Err(bad(lead)) };
    let Some(semi) = rest.find(';') else { return Err(bad(lead)) };
    let name = rest[..semi].trim();
    if name.is_empty() {
        return Err(bad(lead));
    }
    let after = &rest[semi + 1..];
    let after_trim = after.trim_start();
    let Some(json_part) = after_trim.strip_prefix("args=").or_else(|| after_trim.strip_prefix("arguments=")) else {
        return Err(bad(lead + 5 + semi + 1));
    };
    let json_base = base + content.len() - json_part.len();
    let args_lead = json_part.len() - json_part.trim_start().len();
    let value = json::parse_document(json_part.trim()).map_err(|e| json_err(text, &e, json_base + args_lead))?;
    let arguments = arguments_from(&value).map_err(|(c, m)| malformed(c, m, text, json_base + args_lead))?;
    Ok(vec![ToolCall { name: name.to_string(), arguments, format: "bracket" }])
}

fn parse_mistral(text: &str, content_start: usize) -> Result<Vec<ToolCall>, BlockError> {
    let bytes = text.as_bytes();
    let mut p = content_start;
    while p < bytes.len() && is_json_ws(bytes[p]) {
        p += 1;
    }
    if matches!(bytes.get(p), Some(b'[' | b'{')) {
        let (value, _) = json::parse_value_at(text, p).map_err(|e| json_err(text, &e, 0))?;
        return match calls_from_value(&value) {
            Some(Ok(calls)) => Ok(to_calls(calls, "mistral")),
            Some(Err((c, m))) => Err(malformed(c, m, text, p)),
            None => {
                Err(malformed("tool_call.unrecognized", "[TOOL_CALLS] content is not a recognized tool call", text, p))
            }
        };
    }
    // name[ARGS]{...} or name[CALL_ID]id[ARGS]{...}
    let rest = &text[p..];
    let Some(args_rel) = rest.find("[ARGS]") else {
        return Err(malformed(
            "tool_call.unrecognized",
            "expected '[ARGS]' after the tool name in [TOOL_CALLS]",
            text,
            p,
        ));
    };
    let head = &rest[..args_rel];
    let name = head.split("[CALL_ID]").next().unwrap_or("").trim();
    if name.is_empty() {
        return Err(malformed("tool_call.invalid_name", "tool call name must be a non-empty string", text, p));
    }
    let json_start = p + args_rel + "[ARGS]".len();
    let (value, _) = json::parse_value_at(text, json_start).map_err(|e| json_err(text, &e, 0))?;
    let arguments = arguments_from(&value).map_err(|(c, m)| malformed(c, m, text, json_start))?;
    Ok(vec![ToolCall { name: name.to_string(), arguments, format: "mistral" }])
}

fn parse_llama(text: &str, content: &str, base: usize) -> Result<Vec<ToolCall>, BlockError> {
    let trimmed = content.trim_start();
    let lead = content.len() - trimmed.len();
    if trimmed.starts_with('{') || trimmed.starts_with('[') {
        return tagged_json(text, content, base, "llama");
    }
    match python_call_at(text, base + lead, "llama") {
        Some(Ok((call, end))) if text[end..base + content.len()].trim().is_empty() => Ok(vec![call]),
        Some(Ok((_, end))) => {
            Err(malformed("tool_call.trailing_characters", "unexpected text after tool call", text, end))
        }
        Some(Err(e)) => Err(e),
        None => Err(malformed(
            "tool_call.unrecognized",
            "<|python_tag|> content is not a recognized tool call",
            text,
            base + lead,
        )),
    }
}

/// Reads `name="value"` (double or single quotes) from an XML start tag.
fn xml_attr<'t>(tag: &'t str, attr: &str) -> Option<&'t str> {
    let mut from = 0;
    while let Some(rel) = tag[from..].find(attr) {
        let i = from + rel;
        let before_ok = i == 0 || tag.as_bytes()[i - 1].is_ascii_whitespace();
        let rest = tag[i + attr.len()..].trim_start();
        if before_ok {
            if let Some(rest) = rest.strip_prefix('=') {
                let rest = rest.trim_start();
                let q = rest.chars().next()?;
                if q == '"' || q == '\'' {
                    let end = rest[1..].find(q)?;
                    return Some(&rest[1..1 + end]);
                }
            }
        }
        from = i + attr.len();
    }
    None
}

fn xml_unescape(s: &str) -> String {
    s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&apos;", "'").replace("&amp;", "&")
}

fn parse_invoke(text: &str, start: usize) -> Result<Vec<ToolCall>, BlockError> {
    let bad = |msg: &str, at: usize| malformed("tool_call.unrecognized", msg.to_string(), text, at);
    let Some(tag_end_rel) = text[start..].find('>') else {
        return Err(bad("unterminated <invoke> tag", start));
    };
    let tag = &text[start + "<invoke".len()..start + tag_end_rel];
    let name = xml_attr(tag, "name").map(str::trim).filter(|n| !n.is_empty());
    let Some(name) = name else {
        return Err(malformed("tool_call.invalid_name", "<invoke> requires a non-empty name attribute", text, start));
    };
    let body_start = start + tag_end_rel + 1;
    let Some(body_len) = text[body_start..].find("</invoke>") else {
        return Err(malformed("tool_call.unexpected_end", "missing </invoke>", text, text.len()));
    };
    let body = &text[body_start..body_start + body_len];
    let mut arguments: Arguments = Vec::new();
    let mut from = 0;
    while let Some(rel) = body[from..].find("<parameter") {
        let p_start = from + rel;
        let abs = body_start + p_start;
        let Some(gt) = body[p_start..].find('>') else { return Err(bad("unterminated <parameter> tag", abs)) };
        let ptag = &body[p_start + "<parameter".len()..p_start + gt];
        let Some(pname) = xml_attr(ptag, "name") else {
            return Err(bad("<parameter> requires a name attribute", abs));
        };
        let v_start = p_start + gt + 1;
        let Some(v_len) = body[v_start..].find("</parameter>") else {
            return Err(malformed("tool_call.unexpected_end", "missing </parameter>", text, body_start + v_start));
        };
        let raw = body[v_start..v_start + v_len].trim();
        // Values that parse as strict JSON are JSON; everything else is a string.
        let value = json::parse_document(raw).unwrap_or_else(|_| Value::Str(xml_unescape(raw)));
        if arguments.iter().any(|(k, _)| k == pname) {
            return Err(malformed("tool_call.duplicate_argument", format!("duplicate argument '{pname}'"), text, abs));
        }
        arguments.push((pname.to_string(), value));
        from = v_start + v_len + "</parameter>".len();
    }
    Ok(vec![ToolCall { name: name.to_string(), arguments, format: "xml_invoke" }])
}

fn find_tagged(text: &str) -> Vec<Tagged> {
    let mut found = Vec::new();
    for (start, content_start, content) in blocks(text, "<tool_call>", &["</tool_call>"]) {
        found.push(Tagged { start, result: tagged_json(text, content, content_start, "hermes") });
    }
    for (start, content_start, content) in blocks(text, "[TOOL_CALL]", &["[/TOOL_CALL]"]) {
        found.push(Tagged { start, result: parse_bracket(text, content, content_start) });
    }
    for (start, content_start, _) in blocks(text, "[TOOL_CALLS]", &["[TOOL_CALLS]"]) {
        found.push(Tagged { start, result: parse_mistral(text, content_start) });
    }
    for (start, content_start, content) in
        blocks(text, "<|python_tag|>", &["<|eom_id|>", "<|eot_id|>", "<|python_tag|>"])
    {
        found.push(Tagged { start, result: parse_llama(text, content, content_start) });
    }
    let mut from = 0;
    while let Some(rel) = text[from..].find("<invoke") {
        let start = from + rel;
        let next = text.as_bytes().get(start + "<invoke".len());
        if matches!(next, Some(b' ' | b'\t' | b'\n' | b'\r' | b'>')) {
            found.push(Tagged { start, result: parse_invoke(text, start) });
        }
        from = start + "<invoke".len();
    }
    found.sort_by_key(|t| t.start);
    found
}

// ------------------------------------------------------------------ JSON tier

fn find_json_calls(text: &str) -> Result<Vec<ToolCall>, BlockError> {
    let fences: Vec<_> = find_fences(text).into_iter().filter(|f| f.is_json).collect();
    let ranges: Vec<(usize, usize)> = if fences.is_empty() {
        vec![(0, text.len())]
    } else {
        fences.iter().map(|f| (f.content_start, f.content_end)).collect()
    };
    let bytes = text.as_bytes();
    let mut calls = Vec::new();
    for (from, to) in ranges {
        let mut i = from;
        while i < to {
            if bytes[i] != b'{' && bytes[i] != b'[' {
                i += 1;
                continue;
            }
            match json::parse_value_at(text, i) {
                Ok((value, end)) if end <= to => {
                    match calls_from_value(&value) {
                        Some(Ok(found)) => calls.extend(to_calls(found, "json")),
                        Some(Err((code, msg))) => return Err(malformed(code, msg, text, i)),
                        None => {}
                    }
                    i = end;
                }
                Ok(_) => i += 1,
                Err(e) => {
                    if json_like_opener(bytes, i) && looks_like_call(text, i) {
                        return Err(json_err(text, &e, 0));
                    }
                    i += 1;
                }
            }
        }
    }
    Ok(calls)
}

/// A malformed JSON value only counts as a broken tool call if it mentions a
/// call key near its start; otherwise it is unrelated broken JSON.
fn looks_like_call(text: &str, i: usize) -> bool {
    let window: String = text[i..].chars().take(200).collect();
    ["\"name\"", "\"function\"", "\"tool_calls\"", "\"tool_use\"", "\"function_call\""]
        .iter()
        .any(|k| window.contains(k))
}

// ------------------------------------------------------------------ public API

/// Finds every tool call in `text`. Errors if there is none.
pub fn parse_all(text: &str) -> Result<Vec<ToolCall>, BlockError> {
    let tagged = find_tagged(text);
    if !tagged.is_empty() {
        let mut calls = Vec::new();
        for t in tagged {
            calls.extend(t.result?);
        }
        return Ok(calls);
    }
    let json_calls = find_json_calls(text)?;
    if !json_calls.is_empty() {
        return Ok(json_calls);
    }
    let py_calls = scan_python(text)?;
    if !py_calls.is_empty() {
        return Ok(py_calls);
    }
    Err(BlockError::new(ErrorKind::NoToolCallFound, "tool_call.not_found", "no tool call found in text"))
}

/// Finds exactly one tool call.
pub fn parse_one(text: &str) -> Result<ToolCall, BlockError> {
    let mut calls = parse_all(text)?;
    if calls.len() != 1 {
        return Err(BlockError::new(
            ErrorKind::Malformed,
            "tool_call.multiple",
            format!("expected exactly one tool call, found {}; use parse_tool_calls()", calls.len()),
        ));
    }
    Ok(calls.remove(0))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn one(text: &str) -> (String, String, &'static str) {
        let c = parse_one(text).unwrap();
        (c.name, Value::Object(c.arguments).to_json(), c.format)
    }

    #[test]
    fn python_style() {
        assert_eq!(
            one(r#"Call: search(query="rust async", limit=5)"#),
            ("search".into(), r#"{"query": "rust async", "limit": 5}"#.into(), "python")
        );
        assert_eq!(
            one("get_weather(city='Paris', units=None, tags=['a', \"b\"], opts={'x': True},)"),
            (
                "get_weather".into(),
                r#"{"city": "Paris", "units": null, "tags": ["a", "b"], "opts": {"x": true}}"#.into(),
                "python"
            )
        );
        assert_eq!(one("now()").1, "{}");
    }

    #[test]
    fn bracket_and_json() {
        assert_eq!(
            one(r#"[TOOL_CALL]name=search;args={"q":"rust"}[/TOOL_CALL]"#),
            ("search".into(), r#"{"q": "rust"}"#.into(), "bracket")
        );
        assert_eq!(one(r#"{"name": "search", "arguments": {"q": "rust"}}"#).2, "json");
        assert_eq!(
            one(r#"{"type": "function", "function": {"name": "search", "arguments": "{\"q\": \"rust\"}"}}"#).1,
            r#"{"q": "rust"}"#
        );
        assert_eq!(one(r#"{"type": "tool_use", "id": "x", "name": "search", "input": {"q": 1}}"#).0, "search");
    }

    #[test]
    fn tagged_formats() {
        assert_eq!(one(r#"<tool_call>{"name": "f", "arguments": {}}</tool_call>"#).2, "hermes");
        assert_eq!(one(r#"[TOOL_CALLS] [{"name": "f", "arguments": {"a": 1}}]"#).2, "mistral");
        assert_eq!(one(r#"[TOOL_CALLS]f[ARGS]{"a": 1}"#).1, r#"{"a": 1}"#);
        assert_eq!(one(r#"<|python_tag|>{"name": "f", "parameters": {"a": 1}}<|eom_id|>"#).2, "llama");
        assert_eq!(one("<|python_tag|>brave_search.call(query=\"x\")").0, "brave_search.call");
        assert_eq!(
            one(r#"<invoke name="search"><parameter name="q">rust &amp; go</parameter><parameter name="n">5</parameter></invoke>"#).1,
            r#"{"q": "rust & go", "n": 5}"#
        );
    }

    #[test]
    fn multiple_and_errors() {
        let calls = parse_all(r#"<tool_call>{"name": "a", "arguments": {}}</tool_call><tool_call>{"name": "b", "arguments": {}}</tool_call>"#).unwrap();
        assert_eq!(calls.len(), 2);
        assert_eq!(parse_one("a(x=1) b(y=2)").unwrap_err().code, "tool_call.multiple");
        assert_eq!(parse_one("search(5)").unwrap_err().kind, ErrorKind::NoToolCallFound);
        assert_eq!(parse_one("search(q=1, 5)").unwrap_err().code, "tool_call.positional_argument");
        assert_eq!(parse_one(r#"{"name": "f", "arguments": "{bad"}"#).unwrap_err().code, "tool_call.invalid_arguments");
        let e = parse_one(r#"{"name": "search", "arguments": {"q": "rust""#).unwrap_err();
        assert_eq!(e.code, "json.unexpected_end");
        assert!(e.position.is_some());
        assert_eq!(parse_one("Just a normal answer.").unwrap_err().kind, ErrorKind::NoToolCallFound);
        assert_eq!(parse_one(r#"{"name": "Alice", "age": 3}"#).unwrap_err().kind, ErrorKind::NoToolCallFound);
    }
}
