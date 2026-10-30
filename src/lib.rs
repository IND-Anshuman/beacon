//! beacon: deterministic, tested building blocks for AI pipelines.
//!
//! The pure-Rust core lives in the block modules below and never touches
//! Python. The PyO3 module `beacon._beacon_native` (behind the default
//! `python` feature) converts arguments, calls the core, and maps errors to
//! the exception classes defined in `beacon/errors.py`.

pub mod error;
pub mod extract_json;
pub mod hash;
pub mod json;
pub mod normalize;
pub mod parse_tool_call;
pub mod redact;
pub mod repair;
pub mod retry;
pub mod template;
pub mod validate_schema;
pub mod value;

#[cfg(feature = "python")]
mod convert;

#[cfg(feature = "python")]
#[pyo3::pymodule]
mod _beacon_native {
    use pyo3::prelude::*;
    use pyo3::types::{PyDict, PyList, PyString};

    use crate::convert::{
        errors_to_py, hash_py, py_to_value, schema_validation_err, template_value, to_py_err, value_to_py,
    };
    use crate::extract_json::{Kind, Select};
    use crate::hash::{CanonicalHasher, check_length};
    use crate::normalize::{Form, Options};
    use crate::parse_tool_call::ToolCall;
    use crate::redact::Spec;
    use crate::retry::{self, Policy};
    use crate::template::Escape;
    use crate::value::Value;

    #[pymodule_export]
    const VERSION: &str = env!("CARGO_PKG_VERSION");

    /// The Unicode version of the normalization tables, as "major.minor.patch".
    #[pyfunction]
    fn unicode_version() -> String {
        let (a, b, c) = unicode_normalization::UNICODE_VERSION;
        format!("{a}.{b}.{c}")
    }

    #[pyfunction]
    #[pyo3(signature = (source, variables, escape, strict))]
    fn template(
        py: Python<'_>,
        source: &str,
        variables: &Bound<'_, PyDict>,
        escape: &str,
        strict: bool,
    ) -> PyResult<String> {
        let escape = Escape::parse(escape).map_err(|e| to_py_err(py, e))?;
        let mut vars = Vec::with_capacity(variables.len());
        for (k, v) in variables.iter() {
            let name = k.cast::<PyString>()?.to_str()?.to_string();
            let value = template_value(&name, &v)?;
            vars.push((name, value));
        }
        crate::template::render(source, &vars, escape, strict).map_err(|e| to_py_err(py, e))
    }

    #[pyfunction]
    fn template_variables(py: Python<'_>, source: &str) -> PyResult<Vec<String>> {
        crate::template::variables(source).map_err(|e| to_py_err(py, e))
    }

    #[pyfunction]
    #[pyo3(signature = (text, select, kind, required))]
    fn extract_json<'py>(
        py: Python<'py>,
        text: &str,
        select: &str,
        kind: &str,
        required: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let select = Select::parse(select).map_err(|e| to_py_err(py, e))?;
        let kind = Kind::parse(kind).map_err(|e| to_py_err(py, e))?;
        let found = if required {
            Some(crate::extract_json::extract_required(text, select, kind).map_err(|e| to_py_err(py, e))?)
        } else {
            crate::extract_json::extract(text, select, kind).map_err(|e| to_py_err(py, e))?
        };
        match found {
            Some(e) => value_to_py(py, &e.value),
            None => Ok(py.None().into_bound(py)),
        }
    }

    #[pyfunction]
    #[pyo3(signature = (text, select, kind))]
    fn extract_json_detailed<'py>(
        py: Python<'py>,
        text: &str,
        select: &str,
        kind: &str,
    ) -> PyResult<Bound<'py, PyDict>> {
        let select = Select::parse(select).map_err(|e| to_py_err(py, e))?;
        let kind = Kind::parse(kind).map_err(|e| to_py_err(py, e))?;
        let e = crate::extract_json::extract_required(text, select, kind).map_err(|e| to_py_err(py, e))?;
        let d = PyDict::new(py);
        d.set_item("value", value_to_py(py, &e.value)?)?;
        d.set_item("start", e.start)?;
        d.set_item("end", e.end)?;
        d.set_item("source", e.source.as_str())?;
        d.set_item("candidates", e.candidates)?;
        Ok(d)
    }

    fn call_to_py<'py>(py: Python<'py>, call: ToolCall, include_format: bool) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new(py);
        d.set_item("name", call.name)?;
        d.set_item("arguments", value_to_py(py, &Value::Object(call.arguments))?)?;
        if include_format {
            d.set_item("format", call.format)?;
        }
        Ok(d)
    }

    #[pyfunction]
    #[pyo3(signature = (text, include_format))]
    fn parse_tool_call<'py>(py: Python<'py>, text: &str, include_format: bool) -> PyResult<Bound<'py, PyDict>> {
        let call = crate::parse_tool_call::parse_one(text).map_err(|e| to_py_err(py, e))?;
        call_to_py(py, call, include_format)
    }

    #[pyfunction]
    #[pyo3(signature = (text, include_format))]
    fn parse_tool_calls<'py>(py: Python<'py>, text: &str, include_format: bool) -> PyResult<Bound<'py, PyList>> {
        let calls = crate::parse_tool_call::parse_all(text).map_err(|e| to_py_err(py, e))?;
        let list = PyList::empty(py);
        for call in calls {
            list.append(call_to_py(py, call, include_format)?)?;
        }
        Ok(list)
    }

    #[pyfunction]
    fn repair_json<'py>(py: Python<'py>, text: &str) -> PyResult<Bound<'py, PyDict>> {
        let out = crate::repair::repair(text).map_err(|e| to_py_err(py, e))?;
        let d = PyDict::new(py);
        d.set_item("value", value_to_py(py, &out.value)?)?;
        let repairs = PyList::empty(py);
        for r in &out.repairs {
            let rd = PyDict::new(py);
            rd.set_item("kind", r.kind)?;
            rd.set_item("at", r.at)?;
            rd.set_item("detail", &r.detail)?;
            repairs.append(rd)?;
        }
        d.set_item("repairs", repairs)?;
        d.set_item("incomplete", out.incomplete)?;
        Ok(d)
    }

    fn run_validation(
        py: Python<'_>,
        instance: &Bound<'_, PyAny>,
        schema: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<crate::validate_schema::ValidationError>> {
        let instance = py_to_value(instance, "", 0)?;
        let schema = py_to_value(schema, "", 0)?;
        crate::validate_schema::validate(&instance, &schema).map_err(|e| to_py_err(py, e))
    }

    #[pyfunction]
    fn validate_schema(py: Python<'_>, instance: &Bound<'_, PyAny>, schema: &Bound<'_, PyAny>) -> PyResult<()> {
        let errors = run_validation(py, instance, schema)?;
        if errors.is_empty() { Ok(()) } else { Err(schema_validation_err(py, &errors)) }
    }

    #[pyfunction]
    fn schema_errors<'py>(
        py: Python<'py>,
        instance: &Bound<'_, PyAny>,
        schema: &Bound<'_, PyAny>,
    ) -> PyResult<Bound<'py, PyList>> {
        let errors = run_validation(py, instance, schema)?;
        errors_to_py(py, &errors)
    }

    #[pyfunction]
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (text, form, strip_accents, lowercase, remove_control, remove_zero_width, collapse_whitespace, preserve_newlines, strip))]
    fn normalize(
        py: Python<'_>,
        text: &str,
        form: Option<&str>,
        strip_accents: bool,
        lowercase: bool,
        remove_control: bool,
        remove_zero_width: bool,
        collapse_whitespace: bool,
        preserve_newlines: bool,
        strip: bool,
    ) -> PyResult<String> {
        let form = form.map(Form::parse).transpose().map_err(|e| to_py_err(py, e))?;
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
        Ok(crate::normalize::normalize(text, &opts))
    }

    #[pyfunction]
    #[pyo3(signature = (value, length))]
    fn hash_content(py: Python<'_>, value: &Bound<'_, PyAny>, length: usize) -> PyResult<String> {
        let length = check_length(length).map_err(|e| to_py_err(py, e))?;
        let mut h = CanonicalHasher::new();
        hash_py(value, &mut h, "", 0)?;
        Ok(h.finish(length))
    }

    fn spec_labels(py: Python<'_>, policy: &str, exclude: &[String]) -> PyResult<Vec<&'static str>> {
        let labels = crate::redact::policy_labels(policy).map_err(|e| to_py_err(py, e))?;
        for x in exclude {
            if !crate::redact::BUILTIN_LABELS.contains(&x.as_str()) {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "unknown label in exclude: '{x}'; built-in labels are {}",
                    crate::redact::BUILTIN_LABELS.join(", ")
                )));
            }
        }
        Ok(labels.iter().copied().filter(|l| !exclude.iter().any(|x| x == l)).collect())
    }

    #[pyfunction]
    #[pyo3(signature = (text, policy, exclude, patterns, terms, replacement))]
    fn redact(
        py: Python<'_>,
        text: &str,
        policy: &str,
        exclude: Vec<String>,
        patterns: Vec<(String, String)>,
        terms: Vec<(String, Vec<String>)>,
        replacement: &str,
    ) -> PyResult<String> {
        let spec = Spec { labels: spec_labels(py, policy, &exclude)?, custom: &patterns, terms: &terms };
        crate::redact::redact(text, &spec, replacement).map_err(|e| to_py_err(py, e))
    }

    #[pyfunction]
    #[pyo3(signature = (text, policy, exclude, patterns, terms))]
    fn detect_pii<'py>(
        py: Python<'py>,
        text: &str,
        policy: &str,
        exclude: Vec<String>,
        patterns: Vec<(String, String)>,
        terms: Vec<(String, Vec<String>)>,
    ) -> PyResult<Bound<'py, PyList>> {
        let spec = Spec { labels: spec_labels(py, policy, &exclude)?, custom: &patterns, terms: &terms };
        let findings = crate::redact::detect(text, &spec).map_err(|e| to_py_err(py, e))?;
        let list = PyList::empty(py);
        for f in findings {
            let d = PyDict::new(py);
            d.set_item("label", f.label)?;
            d.set_item("start", f.start)?;
            d.set_item("end", f.end)?;
            d.set_item("text", f.text)?;
            list.append(d)?;
        }
        Ok(list)
    }

    fn policy(
        max_attempts: u32,
        base_delay_ms: u64,
        max_delay_ms: u64,
        jitter_percent: u32,
        jitter_key: String,
    ) -> Policy {
        Policy { max_attempts, base_delay_ms, max_delay_ms, jitter_percent, jitter_key }
    }

    /// Returns `(retry, reason, delay_ms, attempt)`.
    #[pyfunction]
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (type_names, status, retry_after, retry_after_ms, attempt, max_attempts, base_delay_ms, max_delay_ms, jitter_percent, jitter_key))]
    fn retry_classify(
        py: Python<'_>,
        type_names: Vec<String>,
        status: Option<i64>,
        retry_after: Option<String>,
        retry_after_ms: Option<String>,
        attempt: u32,
        max_attempts: u32,
        base_delay_ms: u64,
        max_delay_ms: u64,
        jitter_percent: u32,
        jitter_key: String,
    ) -> PyResult<(bool, &'static str, u64, u32)> {
        let status = status.and_then(|s| u16::try_from(s).ok()).filter(|s| (100..=599).contains(s));
        let reason = retry::classify_reason(&type_names, status);
        let after = retry::parse_retry_after(retry_after.as_deref(), retry_after_ms.as_deref());
        let p = policy(max_attempts, base_delay_ms, max_delay_ms, jitter_percent, jitter_key);
        let d = retry::decide(reason, attempt, after, &p).map_err(|e| to_py_err(py, e))?;
        Ok((d.retry, d.reason.as_str(), d.delay_ms, d.attempt))
    }

    #[pyfunction]
    #[pyo3(signature = (attempt, max_attempts, base_delay_ms, max_delay_ms, jitter_percent, jitter_key))]
    fn retry_backoff_ms(
        py: Python<'_>,
        attempt: u32,
        max_attempts: u32,
        base_delay_ms: u64,
        max_delay_ms: u64,
        jitter_percent: u32,
        jitter_key: String,
    ) -> PyResult<u64> {
        let p = policy(max_attempts, base_delay_ms, max_delay_ms, jitter_percent, jitter_key);
        p.check().map_err(|e| to_py_err(py, e))?;
        if attempt == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err("attempt must be at least 1"));
        }
        Ok(retry::backoff_ms(attempt, &p))
    }
}
