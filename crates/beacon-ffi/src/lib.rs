//! C ABI over `beacon-core`: the FFI foundation for native bindings (Go, JVM, C).
//!
//! Every function takes UTF-8, NUL-terminated C strings and returns a freshly
//! allocated UTF-8 C string — free it with [`beacon_string_free`] — or `NULL`
//! on error. After a `NULL`, [`beacon_last_error_code`] and
//! [`beacon_last_error_message`] give the stable beacon error code and message
//! for the current thread (valid until that thread's next beacon call).
//!
//! Structured results are beacon's canonical JSON text, byte-identical to the
//! Python and WebAssembly bindings — the cross-language conformance corpus
//! asserts it. JSON-value inputs (schemas, hash values, tool-call arguments,
//! template variables, citation kinds) are passed as JSON text and parsed with
//! beacon's own strict parser. Deterministic: no clock, RNG, locale, env,
//! network or model.

use std::cell::RefCell;
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::ptr;

use beacon_core::error::{BlockError, ErrorKind};
use beacon_core::extract_json::{self, Kind, Select};
use beacon_core::normalize::{self, Form, Options};
use beacon_core::parse_tool_call::{self, ToolCall};
use beacon_core::redact::{self, Spec};
use beacon_core::template::{self, Escape};
use beacon_core::value::Value;
use beacon_core::{citations, hash, injection, json, partial, repair, validate_schema};

// ------------------------------------------------------------------ errors

thread_local! {
    static LAST_ERROR: RefCell<Option<(CString, CString)>> = const { RefCell::new(None) };
}

fn set_last_error(code: &str, message: &str) {
    let code = CString::new(code).unwrap_or_default();
    let message = CString::new(message.replace('\0', " ")).unwrap_or_default();
    LAST_ERROR.with(|cell| *cell.borrow_mut() = Some((code, message)));
}

fn ffi_err(code: &'static str, message: &str) -> BlockError {
    BlockError::new(ErrorKind::InvalidType, code, message.to_string())
}

/// Stable error code for the last failing call on this thread, or `NULL` if the
/// last call succeeded. Valid until the next beacon call on this thread.
#[unsafe(no_mangle)]
pub extern "C" fn beacon_last_error_code() -> *const c_char {
    LAST_ERROR.with(|cell| match &*cell.borrow() {
        Some((code, _)) => code.as_ptr(),
        None => ptr::null(),
    })
}

/// Human-readable message for the last failing call on this thread, or `NULL`.
/// Valid until the next beacon call on this thread.
#[unsafe(no_mangle)]
pub extern "C" fn beacon_last_error_message() -> *const c_char {
    LAST_ERROR.with(|cell| match &*cell.borrow() {
        Some((_, message)) => message.as_ptr(),
        None => ptr::null(),
    })
}

/// Free a string returned by any `beacon_*` function. Passing `NULL` is a no-op.
///
/// # Safety
/// `s` must be a pointer returned by a `beacon_*` function and not already freed.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_string_free(s: *mut c_char) {
    if !s.is_null() {
        // SAFETY: `s` was produced by `CString::into_raw` in this crate.
        drop(unsafe { CString::from_raw(s) });
    }
}

// ------------------------------------------------------------------ marshalling

/// # Safety
/// `ptr` must be `NULL` or a valid NUL-terminated C string that stays valid for
/// the duration of the call.
unsafe fn as_str<'a>(ptr: *const c_char) -> Result<&'a str, BlockError> {
    if ptr.is_null() {
        return Err(ffi_err("ffi.null_argument", "a required argument was NULL"));
    }
    // SAFETY: the caller upholds the contract above.
    unsafe { CStr::from_ptr(ptr) }
        .to_str()
        .map_err(|_| ffi_err("ffi.invalid_utf8", "argument was not valid UTF-8"))
}

fn finish(result: Result<String, BlockError>) -> *mut c_char {
    match result {
        Ok(s) => match CString::new(s) {
            Ok(cs) => cs.into_raw(),
            Err(_) => {
                set_last_error("ffi.interior_nul", "result contained a NUL byte");
                ptr::null_mut()
            }
        },
        Err(e) => {
            set_last_error(e.code, &e.message);
            ptr::null_mut()
        }
    }
}

/// Run a fallible body, catching panics at the boundary, and marshal the result.
fn run<F: FnOnce() -> Result<String, BlockError>>(f: F) -> *mut c_char {
    LAST_ERROR.with(|cell| *cell.borrow_mut() = None);
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(result) => finish(result),
        Err(_) => {
            set_last_error("ffi.panic", "a panic was caught at the FFI boundary");
            ptr::null_mut()
        }
    }
}

fn parse_json(text: &str, what: &str) -> Result<Value, BlockError> {
    json::parse_document(text)
        .map_err(|e| BlockError::at(ErrorKind::Malformed, e.code, format!("{what}: {}", e.message), text, e.byte))
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

/// # Safety
/// All string pointers must be `NULL` or valid NUL-terminated C strings.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_extract_json(
    text: *const c_char,
    select: *const c_char,
    kind: *const c_char,
    required: c_int,
) -> *mut c_char {
    let text = unsafe { as_str(text) };
    let select = unsafe { as_str(select) };
    let kind = unsafe { as_str(kind) };
    run(move || {
        let sel = Select::parse(select?)?;
        let k = Kind::parse(kind?)?;
        let found = if required != 0 {
            Some(extract_json::extract_required(text?, sel, k)?)
        } else {
            extract_json::extract(text?, sel, k)?
        };
        Ok(match found {
            Some(e) => e.value.to_json(),
            None => "null".to_string(),
        })
    })
}

/// # Safety
/// `text` must be `NULL` or a valid NUL-terminated C string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_repair_json(text: *const c_char) -> *mut c_char {
    let text = unsafe { as_str(text) };
    run(move || {
        let out = repair::repair(text?)?;
        let repairs = Value::Array(
            out.repairs
                .iter()
                .map(|r| obj(vec![("kind", s(r.kind)), ("at", n(r.at as i64)), ("detail", s(&r.detail))]))
                .collect(),
        );
        Ok(obj(vec![("value", out.value), ("repairs", repairs), ("incomplete", Value::Bool(out.incomplete))]).to_json())
    })
}

/// # Safety
/// `text` must be `NULL` or a valid NUL-terminated C string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_parse_partial(text: *const c_char) -> *mut c_char {
    let text = unsafe { as_str(text) };
    run(move || {
        let out = partial::parse_partial(text?);
        Ok(obj(vec![
            ("value", out.value),
            ("complete", Value::Bool(out.complete)),
            ("consumed", n(out.consumed as i64)),
        ])
        .to_json())
    })
}

// ------------------------------------------------------------------ tool calls

fn call_value(c: ToolCall, include_format: bool) -> Value {
    let mut pairs = vec![("name", s(&c.name)), ("arguments", Value::Object(c.arguments))];
    if include_format {
        pairs.push(("format", s(c.format)));
    }
    obj(pairs)
}

/// # Safety
/// `text` must be `NULL` or a valid NUL-terminated C string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_parse_tool_calls(text: *const c_char, include_format: c_int) -> *mut c_char {
    let text = unsafe { as_str(text) };
    run(move || {
        let calls = parse_tool_call::parse_all(text?)?;
        Ok(Value::Array(calls.into_iter().map(|c| call_value(c, include_format != 0)).collect()).to_json())
    })
}

// ------------------------------------------------------------------ schema

/// # Safety
/// Both pointers must be `NULL` or valid NUL-terminated C strings.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_schema_errors(instance: *const c_char, schema: *const c_char) -> *mut c_char {
    let instance = unsafe { as_str(instance) };
    let schema = unsafe { as_str(schema) };
    run(move || {
        let instance = parse_json(instance?, "instance")?;
        let schema = parse_json(schema?, "schema")?;
        let errors = validate_schema::validate(&instance, &schema)?;
        Ok(Value::Array(
            errors
                .iter()
                .map(|e| obj(vec![("path", s(&e.path)), ("keyword", s(e.keyword)), ("message", s(&e.message))]))
                .collect(),
        )
        .to_json())
    })
}

// ------------------------------------------------------------------ normalize / hash

/// # Safety
/// `text` and `form` must be `NULL` or valid NUL-terminated C strings. `form`
/// may be `NULL` to skip Unicode normalization.
#[unsafe(no_mangle)]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn beacon_normalize(
    text: *const c_char,
    form: *const c_char,
    strip_accents: c_int,
    lowercase: c_int,
    remove_control: c_int,
    remove_zero_width: c_int,
    collapse_whitespace: c_int,
    preserve_newlines: c_int,
    strip: c_int,
) -> *mut c_char {
    let text = unsafe { as_str(text) };
    let form = if form.is_null() { None } else { Some(unsafe { as_str(form) }) };
    run(move || {
        let form = match form {
            Some(f) => Some(Form::parse(f?)?),
            None => None,
        };
        let opts = Options {
            form,
            strip_accents: strip_accents != 0,
            lowercase: lowercase != 0,
            remove_control: remove_control != 0,
            remove_zero_width: remove_zero_width != 0,
            collapse_whitespace: collapse_whitespace != 0,
            preserve_newlines: preserve_newlines != 0,
            strip: strip != 0,
        };
        Ok(normalize::normalize(text?, &opts))
    })
}

/// # Safety
/// `json_value` must be `NULL` or a valid NUL-terminated C string (JSON text).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_hash_content(json_value: *const c_char, length: usize) -> *mut c_char {
    let json_value = unsafe { as_str(json_value) };
    run(move || {
        let len = hash::check_length(length)?;
        let value = parse_json(json_value?, "value")?;
        hash::hash_value(&value, len)
    })
}

/// # Safety
/// `parts_json` must be `NULL` or a valid NUL-terminated C string (a JSON array).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_cache_key(parts_json: *const c_char, length: usize) -> *mut c_char {
    unsafe { beacon_hash_content(parts_json, length) }
}

// ------------------------------------------------------------------ redact

fn policy_spec(policy: &str) -> Result<Spec<'static>, BlockError> {
    let labels = redact::policy_labels(policy)?.to_vec();
    Ok(Spec { labels, custom: &[], terms: &[] })
}

/// # Safety
/// All string pointers must be `NULL` or valid NUL-terminated C strings.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_redact(
    text: *const c_char,
    policy: *const c_char,
    replacement: *const c_char,
) -> *mut c_char {
    let text = unsafe { as_str(text) };
    let policy = unsafe { as_str(policy) };
    let replacement = unsafe { as_str(replacement) };
    run(move || {
        let spec = policy_spec(policy?)?;
        redact::redact(text?, &spec, replacement?)
    })
}

/// # Safety
/// Both pointers must be `NULL` or valid NUL-terminated C strings.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_detect_pii(text: *const c_char, policy: *const c_char) -> *mut c_char {
    let text = unsafe { as_str(text) };
    let policy = unsafe { as_str(policy) };
    run(move || {
        let spec = policy_spec(policy?)?;
        let findings = redact::detect(text?, &spec)?;
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
    })
}

// ------------------------------------------------------------------ template

/// # Safety
/// All string pointers must be `NULL` or valid NUL-terminated C strings;
/// `variables_json` is JSON object text.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_template(
    source: *const c_char,
    variables_json: *const c_char,
    escape: *const c_char,
    strict: c_int,
) -> *mut c_char {
    let source = unsafe { as_str(source) };
    let variables_json = unsafe { as_str(variables_json) };
    let escape = unsafe { as_str(escape) };
    run(move || {
        let esc = Escape::parse(escape?)?;
        let mut vars = Vec::new();
        if let Value::Object(entries) = parse_json(variables_json?, "variables")? {
            for (k, v) in entries {
                let text = match &v {
                    Value::Str(t) => t.clone(),
                    Value::Bool(b) => if *b { "True" } else { "False" }.to_string(),
                    Value::Int(_) | Value::BigInt(_) | Value::Float(_) => v.to_json(),
                    _ => {
                        return Err(ffi_err(
                            "template.invalid_value",
                            &format!("template variable '{k}' has unsupported type '{}'", v.type_name()),
                        ));
                    }
                };
                vars.push((k, text));
            }
        }
        template::render(source?, &vars, esc, strict != 0)
    })
}

/// # Safety
/// `source` must be `NULL` or a valid NUL-terminated C string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_template_variables(source: *const c_char) -> *mut c_char {
    let source = unsafe { as_str(source) };
    run(move || {
        let vars = template::variables(source?)?;
        Ok(Value::Array(vars.into_iter().map(Value::Str).collect()).to_json())
    })
}

// ------------------------------------------------------------------ citations

/// # Safety
/// Both pointers must be `NULL` or valid NUL-terminated C strings; `kinds_json`
/// is a JSON array of kind names.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_extract_citations(text: *const c_char, kinds_json: *const c_char) -> *mut c_char {
    let text = unsafe { as_str(text) };
    let kinds_json = unsafe { as_str(kinds_json) };
    run(move || {
        let kinds: Vec<String> = match parse_json(kinds_json?, "kinds")? {
            Value::Array(items) => items.iter().filter_map(|v| v.as_str().map(str::to_string)).collect(),
            _ => citations::ALL_KINDS.iter().map(|k| k.to_string()).collect(),
        };
        let kind_refs: Vec<&str> = kinds.iter().map(String::as_str).collect();
        let cits = citations::extract(text?, &kind_refs)?;
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
    })
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

/// # Safety
/// Both pointers must be `NULL` or valid NUL-terminated C strings.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_detect_injection(text: *const c_char, policy: *const c_char) -> *mut c_char {
    let text = unsafe { as_str(text) };
    let policy = unsafe { as_str(policy) };
    run(move || {
        let findings = injection::detect(text?, policy?)?;
        Ok(findings_value(findings).to_json())
    })
}

/// # Safety
/// Both pointers must be `NULL` or valid NUL-terminated C strings; `arguments_json`
/// is JSON text.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn beacon_scan_arguments(arguments_json: *const c_char, policy: *const c_char) -> *mut c_char {
    let arguments_json = unsafe { as_str(arguments_json) };
    let policy = unsafe { as_str(policy) };
    run(move || {
        let args = parse_json(arguments_json?, "arguments")?;
        let findings = injection::scan_arguments(&args, policy?)?;
        Ok(findings_value(findings).to_json())
    })
}

// ------------------------------------------------------------------ tests

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
mod tests {
    use super::*;

    /// Call an FFI fn, return the result String (freeing the C buffer), or the
    /// error code on NULL.
    fn take(ptr: *mut c_char) -> Result<String, String> {
        if ptr.is_null() {
            let code = beacon_last_error_code();
            let code = if code.is_null() {
                String::new()
            } else {
                unsafe { CStr::from_ptr(code) }.to_string_lossy().into_owned()
            };
            return Err(code);
        }
        let out = unsafe { CStr::from_ptr(ptr) }.to_string_lossy().into_owned();
        unsafe { beacon_string_free(ptr) };
        Ok(out)
    }

    fn c(s: &str) -> CString {
        CString::new(s).expect("no interior NUL in test input")
    }

    #[test]
    fn extract_json_ok() {
        let out = unsafe {
            beacon_extract_json(c("say: {\"a\": 1} ok").as_ptr(), c("first").as_ptr(), c("auto").as_ptr(), 1)
        };
        assert_eq!(take(out).unwrap(), "{\"a\": 1}");
    }

    #[test]
    fn repair_and_partial() {
        let r = unsafe { beacon_repair_json(c("{\"a\": 1, \"b\": 2,}").as_ptr()) };
        let r = take(r).unwrap();
        assert!(r.contains("trailing_comma"));
        let p = unsafe { beacon_parse_partial(c("{\"intent\": \"canc").as_ptr()) };
        assert!(take(p).unwrap().contains("\"complete\": false"));
    }

    #[test]
    fn hash_is_stable_and_normalize_works() {
        let a = unsafe { beacon_hash_content(c("{\"a\": 1, \"b\": 2}").as_ptr(), 16) };
        let b = unsafe { beacon_hash_content(c("{\"b\": 2, \"a\": 1}").as_ptr(), 16) };
        assert_eq!(take(a).unwrap(), take(b).unwrap()); // key order irrelevant
        let norm = unsafe {
            beacon_normalize(c("Hello   World\n\n").as_ptr(), c("NFKC").as_ptr(), 0, 0, 1, 1, 1, 0, 1)
        };
        assert_eq!(take(norm).unwrap(), "Hello World");
    }

    #[test]
    fn redact_and_tool_calls() {
        let r = unsafe {
            beacon_redact(c("Email alice@example.com now").as_ptr(), c("default").as_ptr(), c("[REDACTED:{label}]").as_ptr())
        };
        assert_eq!(take(r).unwrap(), "Email [REDACTED:email] now");
        let t = unsafe { beacon_parse_tool_calls(c("search(query=\"rust\", limit=5)").as_ptr(), 0) };
        assert!(take(t).unwrap().contains("\"search\""));
    }

    #[test]
    fn null_argument_sets_error_code() {
        let out = unsafe { beacon_repair_json(ptr::null()) };
        assert_eq!(take(out).unwrap_err(), "ffi.null_argument");
    }

    #[test]
    fn invalid_json_reports_beacon_code() {
        let out = unsafe { beacon_hash_content(c("{not json").as_ptr(), 16) };
        let err = take(out).unwrap_err();
        assert!(err.starts_with("json."), "unexpected code: {err}");
    }

    #[test]
    fn free_null_is_safe() {
        unsafe { beacon_string_free(ptr::null_mut()) };
    }

    #[test]
    fn success_clears_last_error() {
        let _ = take(unsafe { beacon_repair_json(ptr::null()) }); // set an error
        let ok = unsafe { beacon_template_variables(c("{a} {b}").as_ptr()) };
        assert!(take(ok).is_ok());
        assert!(beacon_last_error_code().is_null()); // cleared on the next call
    }
}
