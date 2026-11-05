//! WebAssembly / TypeScript bindings to beacon's Rust core.
//!
//! These are thin wrappers over the exact same `beacon-core` code the Python
//! wheels run, compiled to `wasm32`. Structured results are returned as
//! beacon's canonical JSON text (so output is byte-identical across languages);
//! the hand-written facade in the npm package parses them into typed objects.
//! Errors are thrown as JS `Error`s whose `code` property carries beacon's
//! stable error code.
//!
//! JSON-value inputs (schemas, hash values, tool-call arguments, template
//! variables) are passed as JSON text and parsed with beacon's own strict
//! parser, so numbers keep their integer/float distinction across the boundary.

use beacon_core::citations;
use beacon_core::error::{BlockError, ErrorKind};
use beacon_core::extract_json::{self, Kind, Select};
use beacon_core::hash;
use beacon_core::injection;
use beacon_core::json;
use beacon_core::normalize::{self, Form, Options};
use beacon_core::parse_tool_call::{self, ToolCall};
use beacon_core::redact::{self, Spec};
use beacon_core::repair;
use beacon_core::retry::{self, Policy};
use beacon_core::template::{self, Escape};
use beacon_core::partial;
use beacon_core::validate_schema;
use beacon_core::value::Value;
use wasm_bindgen::prelude::*;

// ------------------------------------------------------------------ helpers

/// Builds a JS `Error` carrying beacon's stable error `code`.
fn to_err(e: BlockError) -> JsValue {
    let err = js_sys::Error::new(&e.message);
    err.set_name("BeaconError");
    let _ = js_sys::Reflect::set(&err, &JsValue::from_str("code"), &JsValue::from_str(e.code));
    err.into()
}

fn parse_json(text: &str, what: &str) -> Result<Value, JsValue> {
    json::parse_document(text)
        .map_err(|e| to_err(BlockError::at(ErrorKind::Malformed, e.code, format!("{what}: {}", e.message), text, e.byte)))
}

fn obj(pairs: Vec<(&str, Value)>) -> Value {
    Value::Object(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
}

fn s(v: &str) -> Value {
    Value::Str(v.to_string())
}

fn n(x: i64) -> Value {
    Value::Int(x)
}

// ------------------------------------------------------------------ extract / repair / partial

#[wasm_bindgen(js_name = extractJson)]
pub fn extract_json(text: &str, select: &str, kind: &str, required: bool) -> Result<String, JsValue> {
    let sel = Select::parse(select).map_err(to_err)?;
    let k = Kind::parse(kind).map_err(to_err)?;
    let found = if required {
        Some(extract_json::extract_required(text, sel, k).map_err(to_err)?)
    } else {
        extract_json::extract(text, sel, k).map_err(to_err)?
    };
    Ok(match found {
        Some(e) => e.value.to_json(),
        None => "null".to_string(),
    })
}

#[wasm_bindgen(js_name = extractJsonDetailed)]
pub fn extract_json_detailed(text: &str, select: &str, kind: &str) -> Result<String, JsValue> {
    let sel = Select::parse(select).map_err(to_err)?;
    let k = Kind::parse(kind).map_err(to_err)?;
    let e = extract_json::extract_required(text, sel, k).map_err(to_err)?;
    Ok(obj(vec![
        ("value", e.value),
        ("start", n(e.start as i64)),
        ("end", n(e.end as i64)),
        ("source", s(e.source.as_str())),
        ("candidates", n(e.candidates as i64)),
    ])
    .to_json())
}

#[wasm_bindgen(js_name = repairJson)]
pub fn repair_json(text: &str) -> Result<String, JsValue> {
    let out = repair::repair(text).map_err(to_err)?;
    let repairs = Value::Array(
        out.repairs
            .iter()
            .map(|r| obj(vec![("kind", s(r.kind)), ("at", n(r.at as i64)), ("detail", s(&r.detail))]))
            .collect(),
    );
    Ok(obj(vec![("value", out.value), ("repairs", repairs), ("incomplete", Value::Bool(out.incomplete))]).to_json())
}

#[wasm_bindgen(js_name = parsePartial)]
pub fn parse_partial(text: &str) -> String {
    let out = partial::parse_partial(text);
    obj(vec![
        ("value", out.value),
        ("complete", Value::Bool(out.complete)),
        ("consumed", n(out.consumed as i64)),
    ])
    .to_json()
}

// ------------------------------------------------------------------ tool calls

fn call_value(c: ToolCall, include_format: bool) -> Value {
    let mut pairs = vec![("name", s(&c.name)), ("arguments", Value::Object(c.arguments))];
    if include_format {
        pairs.push(("format", s(c.format)));
    }
    obj(pairs)
}

#[wasm_bindgen(js_name = parseToolCall)]
pub fn parse_tool_call(text: &str, include_format: bool) -> Result<String, JsValue> {
    let c = parse_tool_call::parse_one(text).map_err(to_err)?;
    Ok(call_value(c, include_format).to_json())
}

#[wasm_bindgen(js_name = parseToolCalls)]
pub fn parse_tool_calls(text: &str, include_format: bool) -> Result<String, JsValue> {
    let calls = parse_tool_call::parse_all(text).map_err(to_err)?;
    Ok(Value::Array(calls.into_iter().map(|c| call_value(c, include_format)).collect()).to_json())
}

// ------------------------------------------------------------------ schema

fn run_validation(instance_text: &str, schema_text: &str) -> Result<Vec<validate_schema::ValidationError>, JsValue> {
    let instance = parse_json(instance_text, "instance")?;
    let schema = parse_json(schema_text, "schema")?;
    validate_schema::validate(&instance, &schema).map_err(to_err)
}

#[wasm_bindgen(js_name = validateSchema)]
pub fn validate_schema(instance_text: &str, schema_text: &str) -> Result<(), JsValue> {
    let errors = run_validation(instance_text, schema_text)?;
    if errors.is_empty() {
        return Ok(());
    }
    let err = js_sys::Error::new(&validate_schema::format_errors(&errors));
    err.set_name("SchemaValidationError");
    let _ = js_sys::Reflect::set(&err, &JsValue::from_str("code"), &JsValue::from_str("schema.validation_failed"));
    Err(err.into())
}

#[wasm_bindgen(js_name = schemaErrors)]
pub fn schema_errors(instance_text: &str, schema_text: &str) -> Result<String, JsValue> {
    let errors = run_validation(instance_text, schema_text)?;
    Ok(Value::Array(
        errors
            .iter()
            .map(|e| obj(vec![("path", s(&e.path)), ("keyword", s(e.keyword)), ("message", s(&e.message))]))
            .collect(),
    )
    .to_json())
}

// ------------------------------------------------------------------ normalize / hash

#[wasm_bindgen(js_name = normalize)]
#[allow(clippy::too_many_arguments)]
pub fn normalize(
    text: &str,
    form: Option<String>,
    strip_accents: bool,
    lowercase: bool,
    remove_control: bool,
    remove_zero_width: bool,
    collapse_whitespace: bool,
    preserve_newlines: bool,
    strip: bool,
) -> Result<String, JsValue> {
    let form = match form.as_deref() {
        Some(f) => Some(Form::parse(f).map_err(to_err)?),
        None => None,
    };
    let opts = Options {
        form,
        strip_accents,
        lowercase,
        remove_control,
        remove_zero_width,
        collapse_whitespace,
        preserve_newlines,
        strip,
    };
    Ok(normalize::normalize(text, &opts))
}

#[wasm_bindgen(js_name = hashContent)]
pub fn hash_content(json_text: &str, length: usize) -> Result<String, JsValue> {
    let len = hash::check_length(length).map_err(to_err)?;
    let value = parse_json(json_text, "value")?;
    hash::hash_value(&value, len).map_err(to_err)
}

#[wasm_bindgen(js_name = cacheKey)]
pub fn cache_key(parts_json_text: &str, length: usize) -> Result<String, JsValue> {
    // `parts_json_text` is a JSON array of the cacheable prompt parts.
    hash_content(parts_json_text, length)
}

// ------------------------------------------------------------------ redact

#[wasm_bindgen(js_name = redact)]
pub fn redact(text: &str, policy: &str, replacement: &str) -> Result<String, JsValue> {
    let labels = redact::policy_labels(policy).map_err(to_err)?.to_vec();
    let spec = Spec { labels, custom: &[], terms: &[] };
    redact::redact(text, &spec, replacement).map_err(to_err)
}

#[wasm_bindgen(js_name = detectPii)]
pub fn detect_pii(text: &str, policy: &str) -> Result<String, JsValue> {
    let labels = redact::policy_labels(policy).map_err(to_err)?.to_vec();
    let spec = Spec { labels, custom: &[], terms: &[] };
    let findings = redact::detect(text, &spec).map_err(to_err)?;
    Ok(Value::Array(
        findings
            .iter()
            .map(|f| {
                obj(vec![
                    ("label", s(&f.label)),
                    ("start", n(f.start as i64)),
                    ("end", n(f.end as i64)),
                    ("text", s(&f.text)),
                ])
            })
            .collect(),
    )
    .to_json())
}

// ------------------------------------------------------------------ template

#[wasm_bindgen(js_name = template)]
pub fn template(source: &str, variables_json_text: &str, escape: &str, strict: bool) -> Result<String, JsValue> {
    let esc = Escape::parse(escape).map_err(to_err)?;
    let mut vars = Vec::new();
    if let Value::Object(entries) = parse_json(variables_json_text, "variables")? {
        for (k, v) in entries {
            let text = match &v {
                Value::Str(t) => t.clone(),
                Value::Bool(b) => if *b { "True" } else { "False" }.to_string(),
                Value::Int(_) | Value::BigInt(_) | Value::Float(_) => v.to_json(),
                _ => {
                    return Err(to_err(BlockError::new(
                        ErrorKind::InvalidType,
                        "template.invalid_value",
                        format!("template variable '{k}' has unsupported type '{}'", v.type_name()),
                    )));
                }
            };
            vars.push((k, text));
        }
    }
    template::render(source, &vars, esc, strict).map_err(to_err)
}

#[wasm_bindgen(js_name = templateVariables)]
pub fn template_variables(source: &str) -> Result<String, JsValue> {
    let vars = template::variables(source).map_err(to_err)?;
    Ok(Value::Array(vars.into_iter().map(Value::Str).collect()).to_json())
}

// ------------------------------------------------------------------ citations

#[wasm_bindgen(js_name = extractCitations)]
pub fn extract_citations(text: &str, kinds_json_text: &str) -> Result<String, JsValue> {
    let kinds: Vec<String> = match parse_json(kinds_json_text, "kinds")? {
        Value::Array(items) => items.iter().filter_map(|v| v.as_str().map(str::to_string)).collect(),
        _ => citations::ALL_KINDS.iter().map(|k| k.to_string()).collect(),
    };
    let kind_refs: Vec<&str> = kinds.iter().map(String::as_str).collect();
    let cits = citations::extract(text, &kind_refs).map_err(to_err)?;
    Ok(Value::Array(
        cits.into_iter()
            .map(|c| {
                obj(vec![
                    ("kind", s(c.kind)),
                    ("ref", s(&c.reference)),
                    ("start", n(c.start as i64)),
                    ("end", n(c.end as i64)),
                    ("text", s(&c.text)),
                ])
            })
            .collect(),
    )
    .to_json())
}

// ------------------------------------------------------------------ injection

fn findings_value(findings: Vec<injection::Finding>) -> Value {
    Value::Array(
        findings
            .into_iter()
            .map(|f| {
                obj(vec![
                    ("label", s(f.label)),
                    ("severity", s(f.severity)),
                    ("start", n(f.start as i64)),
                    ("end", n(f.end as i64)),
                    ("text", s(&f.text)),
                    ("path", s(&f.path)),
                ])
            })
            .collect(),
    )
}

#[wasm_bindgen(js_name = detectInjection)]
pub fn detect_injection(text: &str, policy: &str) -> Result<String, JsValue> {
    let findings = injection::detect(text, policy).map_err(to_err)?;
    Ok(findings_value(findings).to_json())
}

#[wasm_bindgen(js_name = scanArguments)]
pub fn scan_arguments(arguments_json_text: &str, policy: &str) -> Result<String, JsValue> {
    let args = parse_json(arguments_json_text, "arguments")?;
    let findings = injection::scan_arguments(&args, policy).map_err(to_err)?;
    Ok(findings_value(findings).to_json())
}

// ------------------------------------------------------------------ retry

#[wasm_bindgen(js_name = retryClassify)]
#[allow(clippy::too_many_arguments)]
pub fn retry_classify(
    type_names_json: &str,
    status: Option<i32>,
    retry_after: Option<String>,
    retry_after_ms: Option<String>,
    attempt: u32,
    max_attempts: u32,
    base_delay_ms: f64,
    max_delay_ms: f64,
    jitter_percent: u32,
    jitter_key: String,
) -> Result<String, JsValue> {
    let type_names: Vec<String> = match parse_json(type_names_json, "type_names")? {
        Value::Array(items) => items.iter().filter_map(|v| v.as_str().map(str::to_string)).collect(),
        _ => Vec::new(),
    };
    let status = status.and_then(|s| u16::try_from(s).ok()).filter(|s| (100..=599).contains(s));
    let reason = retry::classify_reason(&type_names, status);
    let after = retry::parse_retry_after(retry_after.as_deref(), retry_after_ms.as_deref());
    let policy = Policy {
        max_attempts,
        base_delay_ms: base_delay_ms as u64,
        max_delay_ms: max_delay_ms as u64,
        jitter_percent,
        jitter_key,
    };
    let d = retry::decide(reason, attempt, after, &policy).map_err(to_err)?;
    Ok(obj(vec![
        ("retry", Value::Bool(d.retry)),
        ("reason", s(d.reason.as_str())),
        ("delay_ms", n(d.delay_ms as i64)),
        ("attempt", n(d.attempt as i64)),
    ])
    .to_json())
}

#[wasm_bindgen(js_name = retryBackoffMs)]
#[allow(clippy::too_many_arguments)]
pub fn retry_backoff_ms(
    attempt: u32,
    max_attempts: u32,
    base_delay_ms: f64,
    max_delay_ms: f64,
    jitter_percent: u32,
    jitter_key: String,
) -> Result<f64, JsValue> {
    let policy = Policy {
        max_attempts,
        base_delay_ms: base_delay_ms as u64,
        max_delay_ms: max_delay_ms as u64,
        jitter_percent,
        jitter_key,
    };
    policy.check().map_err(to_err)?;
    if attempt == 0 {
        return Err(to_err(BlockError::invalid_argument("retry.invalid_attempt", "attempt must be at least 1")));
    }
    Ok(retry::backoff_ms(attempt, &policy) as f64)
}
