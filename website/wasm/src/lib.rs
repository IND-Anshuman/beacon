//! A tiny WebAssembly bridge to beacon's Rust core for the docs playground.
//!
//! Protocol (no wasm-bindgen): the host writes a UTF-8 JSON request into
//! memory obtained from `alloc`, calls `call(ptr, len)`, and gets back a
//! `u64` packing `(result_ptr << 32) | result_len`. The result is UTF-8 JSON:
//! `{"ok": ...}` or `{"error": {"kind", "code", "message", "position"}}`.
//! The host frees both buffers with `dealloc`.
//!
//! Requests are parsed with beacon's own strict JSON parser and every block
//! runs the exact code the Python package runs, so results are identical.

use beacon::error::{BlockError, ErrorKind};
use beacon::extract_json::{self, Kind, Select};
use beacon::hash::hash_value;
use beacon::json::parse_document;
use beacon::normalize::{self, Form, Options};
use beacon::parse_tool_call;
use beacon::redact::{self, Spec};
use beacon::retry::{self, Policy};
use beacon::template::{self, Escape};
use beacon::validate_schema;
use beacon::value::{Value, write_json_string};

#[unsafe(no_mangle)]
pub extern "C" fn alloc(len: usize) -> *mut u8 {
    let mut buf = Vec::<u8>::with_capacity(len.max(1));
    let ptr = buf.as_mut_ptr();
    std::mem::forget(buf);
    ptr
}

/// # Safety
/// `ptr`/`cap` must come from `alloc` (or a result of `call`) and be freed once.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn dealloc(ptr: *mut u8, cap: usize) {
    if !ptr.is_null() {
        drop(unsafe { Vec::from_raw_parts(ptr, 0, cap.max(1)) });
    }
}

/// # Safety
/// `ptr` must point to `len` initialized bytes obtained from `alloc`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn call(ptr: *const u8, len: usize) -> u64 {
    let bytes = unsafe { std::slice::from_raw_parts(ptr, len) };
    let out = match std::str::from_utf8(bytes) {
        Ok(text) => handle(text),
        Err(_) => error_json("bridge", "bridge.utf8", "request is not valid UTF-8", None),
    };
    let mut out = out.into_bytes();
    out.shrink_to_fit();
    let (p, l) = (out.as_mut_ptr(), out.len());
    std::mem::forget(out);
    ((p as u64) << 32) | (l as u64)
}

// ------------------------------------------------------------------ helpers

fn quote(s: &str) -> String {
    let mut out = String::new();
    write_json_string(s, &mut out);
    out
}

fn kind_name(kind: ErrorKind) -> &'static str {
    match kind {
        ErrorKind::Malformed => "MalformedOutputError",
        ErrorKind::NoJsonFound => "NoJSONFoundError",
        ErrorKind::NoToolCallFound => "NoToolCallFoundError",
        ErrorKind::TemplateSyntax => "TemplateSyntaxError",
        ErrorKind::MissingVariable => "MissingVariableError",
        ErrorKind::ExtraVariable => "ExtraVariableError",
        ErrorKind::Schema => "SchemaError",
        ErrorKind::InvalidArgument => "ValueError",
        ErrorKind::InvalidType => "TypeError",
    }
}

fn error_json(kind: &str, code: &str, message: &str, pos: Option<(usize, usize, usize)>) -> String {
    let position = match pos {
        Some((o, l, c)) => format!("{{\"offset\": {o}, \"line\": {l}, \"column\": {c}}}"),
        None => "null".to_string(),
    };
    format!(
        "{{\"error\": {{\"kind\": {}, \"code\": {}, \"message\": {}, \"position\": {position}}}}}",
        quote(kind),
        quote(code),
        quote(message)
    )
}

fn block_error(e: &BlockError) -> String {
    error_json(kind_name(e.kind), e.code, &e.message, e.position.map(|p| (p.offset, p.line, p.column)))
}

fn ok(v: &Value) -> String {
    format!("{{\"ok\": {}}}", v.to_json())
}

fn obj(pairs: Vec<(&str, Value)>) -> Value {
    Value::Object(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
}

fn s(v: &str) -> Value {
    Value::Str(v.to_string())
}

fn arg_str<'a>(req: &'a Value, key: &str, default: &'a str) -> &'a str {
    req.get(key).and_then(Value::as_str).unwrap_or(default)
}

fn arg_bool(req: &Value, key: &str, default: bool) -> bool {
    match req.get(key) {
        Some(Value::Bool(b)) => *b,
        _ => default,
    }
}

/// A JSON value given either directly (`key`) or as JSON text (`key_text`),
/// parsed with beacon's strict parser so error positions point into that text.
fn arg_json(req: &Value, key: &str, default: Value) -> Result<Value, BlockError> {
    if let Some(Value::Str(text)) = req.get(&format!("{key}_text")) {
        return parse_document(text).map_err(|e| {
            BlockError::at(ErrorKind::Malformed, e.code, format!("{key}: {}", e.message), text, e.byte)
        });
    }
    Ok(req.get(key).cloned().unwrap_or(default))
}

fn arg_int(req: &Value, key: &str, default: i64) -> i64 {
    match req.get(key) {
        Some(Value::Int(i)) => *i,
        _ => default,
    }
}

// ------------------------------------------------------------------ dispatch

fn handle(text: &str) -> String {
    let req = match parse_document(text) {
        Ok(v) => v,
        Err(e) => return error_json("bridge", e.code, &format!("bad request: {}", e.message), None),
    };
    let op = arg_str(&req, "op", "");
    let result = match op {
        "extract_json" => op_extract(&req),
        "parse_tool_calls" => op_tool_calls(&req),
        "validate_schema" => op_validate(&req),
        "template" => op_template(&req),
        "normalize" => op_normalize(&req),
        "hash_content" => op_hash(&req),
        "redact" => op_redact(&req),
        "retry" => op_retry(&req),
        other => return error_json("bridge", "bridge.unknown_op", &format!("unknown op {other:?}"), None),
    };
    match result {
        Ok(v) => ok(&v),
        Err(e) => block_error(&e),
    }
}

fn op_extract(req: &Value) -> Result<Value, BlockError> {
    let text = arg_str(req, "text", "");
    let select = Select::parse(arg_str(req, "select", "first"))?;
    let kind = Kind::parse(arg_str(req, "kind", "auto"))?;
    let e = extract_json::extract_required(text, select, kind)?;
    Ok(obj(vec![
        ("value", e.value),
        ("start", Value::Int(e.start as i64)),
        ("end", Value::Int(e.end as i64)),
        ("source", s(e.source.as_str())),
        ("candidates", Value::Int(e.candidates as i64)),
    ]))
}

fn op_tool_calls(req: &Value) -> Result<Value, BlockError> {
    let calls = parse_tool_call::parse_all(arg_str(req, "text", ""))?;
    Ok(Value::Array(
        calls
            .into_iter()
            .map(|c| obj(vec![("name", s(&c.name)), ("arguments", Value::Object(c.arguments)), ("format", s(c.format))]))
            .collect(),
    ))
}

fn op_validate(req: &Value) -> Result<Value, BlockError> {
    let instance = arg_json(req, "instance", Value::Null)?;
    let schema = arg_json(req, "schema", Value::Bool(true))?;
    let errors = validate_schema::validate(&instance, &schema)?;
    Ok(obj(vec![
        ("valid", Value::Bool(errors.is_empty())),
        (
            "errors",
            Value::Array(
                errors
                    .into_iter()
                    .map(|e| obj(vec![("path", s(&e.path)), ("keyword", s(e.keyword)), ("message", s(&e.message))]))
                    .collect(),
            ),
        ),
    ]))
}

fn op_template(req: &Value) -> Result<Value, BlockError> {
    let source = arg_str(req, "source", "");
    let escape = Escape::parse(arg_str(req, "escape", "xml"))?;
    let strict = arg_bool(req, "strict", true);
    let mut vars = Vec::new();
    if let Value::Object(entries) = &arg_json(req, "variables", Value::Object(Vec::new()))? {
        for (k, v) in entries {
            let text = match v {
                Value::Str(t) => t.clone(),
                Value::Bool(b) => if *b { "True" } else { "False" }.to_string(),
                Value::Int(_) | Value::BigInt(_) | Value::Float(_) => v.to_json(),
                _ => {
                    return Err(BlockError::new(
                        ErrorKind::InvalidType,
                        "template.invalid_value",
                        format!("template variable '{k}' has unsupported type '{}'", v.type_name()),
                    ));
                }
            };
            vars.push((k.clone(), text));
        }
    }
    template::render(source, &vars, escape, strict).map(Value::Str)
}

fn op_normalize(req: &Value) -> Result<Value, BlockError> {
    let form = match req.get("form") {
        Some(Value::Null) => None,
        Some(Value::Str(f)) => Some(Form::parse(f)?),
        _ => Some(Form::Nfkc),
    };
    let d = Options::default();
    let opts = Options {
        form,
        strip_accents: arg_bool(req, "strip_accents", d.strip_accents),
        lowercase: arg_bool(req, "lowercase", d.lowercase),
        remove_control: arg_bool(req, "remove_control", d.remove_control),
        remove_zero_width: arg_bool(req, "remove_zero_width", d.remove_zero_width),
        collapse_whitespace: arg_bool(req, "collapse_whitespace", d.collapse_whitespace),
        preserve_newlines: arg_bool(req, "preserve_newlines", d.preserve_newlines),
        strip: arg_bool(req, "strip", d.strip),
    };
    Ok(Value::Str(normalize::normalize(arg_str(req, "text", ""), &opts)))
}

fn op_hash(req: &Value) -> Result<Value, BlockError> {
    let value = arg_json(req, "value", Value::Null)?;
    let length = usize::try_from(arg_int(req, "length", 16)).unwrap_or(0);
    hash_value(&value, length).map(Value::Str)
}

fn op_redact(req: &Value) -> Result<Value, BlockError> {
    let text = arg_str(req, "text", "");
    let labels = redact::policy_labels(arg_str(req, "policy", "default"))?.to_vec();
    let spec = Spec { labels, custom: &[], terms: &[] };
    let redacted = redact::redact(text, &spec, arg_str(req, "replacement", "[REDACTED:{label}]"))?;
    let findings = redact::detect(text, &spec)?;
    Ok(obj(vec![
        ("redacted", Value::Str(redacted)),
        (
            "findings",
            Value::Array(
                findings
                    .into_iter()
                    .map(|f| {
                        obj(vec![
                            ("label", s(&f.label)),
                            ("start", Value::Int(f.start as i64)),
                            ("end", Value::Int(f.end as i64)),
                            ("text", s(&f.text)),
                        ])
                    })
                    .collect(),
            ),
        ),
    ]))
}

fn op_retry(req: &Value) -> Result<Value, BlockError> {
    let status = u16::try_from(arg_int(req, "status", 429)).ok();
    let attempts = u32::try_from(arg_int(req, "attempts", 6)).unwrap_or(6).clamp(1, 12);
    let policy = Policy {
        max_attempts: u32::try_from(arg_int(req, "max_attempts", 5)).unwrap_or(5),
        base_delay_ms: u64::try_from(arg_int(req, "base_delay_ms", 1000)).unwrap_or(1000),
        max_delay_ms: u64::try_from(arg_int(req, "max_delay_ms", 60_000)).unwrap_or(60_000),
        jitter_percent: u32::try_from(arg_int(req, "jitter_percent", 20)).unwrap_or(20),
        jitter_key: arg_str(req, "jitter_key", "").to_string(),
    };
    let reason = retry::classify_reason(&[], status);
    let mut schedule = Vec::new();
    for attempt in 1..=attempts {
        let d = retry::decide(reason, attempt, None, &policy)?;
        schedule.push(obj(vec![
            ("attempt", Value::Int(i64::from(attempt))),
            ("action", s(if d.retry { "retry" } else { "fail" })),
            ("delay_ms", Value::Int(d.delay_ms as i64)),
        ]));
    }
    Ok(obj(vec![
        ("reason", s(reason.as_str())),
        ("retryable", Value::Bool(reason.retryable())),
        ("schedule", Value::Array(schedule)),
    ]))
}
