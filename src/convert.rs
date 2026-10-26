//! Conversions between Python objects and the core types, and mapping of
//! [`BlockError`]s to Python exceptions. Only compiled with the `python`
//! feature.

use pyo3::IntoPyObjectExt;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

use crate::error::{BlockError, ErrorKind};
use crate::hash::CanonicalHasher;
use crate::validate_schema::ValidationError;
use crate::value::Value;

/// Maximum nesting depth accepted when converting Python data.
pub const MAX_DEPTH: usize = 512;

fn type_name(obj: &Bound<'_, PyAny>) -> String {
    obj.get_type().name().map(|n| n.to_string()).unwrap_or_else(|_| "?".to_string())
}

fn location(path: &str) -> String {
    if path.is_empty() { "the top level".to_string() } else { format!("'{path}'") }
}

fn depth_error(path: &str) -> PyErr {
    PyValueError::new_err(format!("value is nested deeper than {MAX_DEPTH} levels at {}", location(path)))
}

fn child(path: &str, key: &str) -> String {
    let mut p = String::with_capacity(path.len() + key.len() + 1);
    p.push_str(path);
    p.push('/');
    p.push_str(&key.replace('~', "~0").replace('/', "~1"));
    p
}

/// Canonical decimal text of a Python int (handles any size).
fn int_decimal(obj: &Bound<'_, PyAny>) -> PyResult<Option<i64>> {
    match obj.extract::<i64>() {
        Ok(i) => Ok(Some(i)),
        Err(_) => Ok(None),
    }
}

/// Converts JSON-like Python data to a [`Value`]. `path` is a JSON Pointer
/// used in error messages.
pub fn py_to_value(obj: &Bound<'_, PyAny>, path: &str, depth: usize) -> PyResult<Value> {
    if depth > MAX_DEPTH {
        return Err(depth_error(path));
    }
    if obj.is_none() {
        return Ok(Value::Null);
    }
    if let Ok(b) = obj.cast::<PyBool>() {
        return Ok(Value::Bool(b.is_true()));
    }
    if obj.is_instance_of::<PyInt>() {
        return Ok(match int_decimal(obj)? {
            Some(i) => Value::Int(i),
            None => Value::BigInt(obj.str()?.to_str()?.to_string()),
        });
    }
    if let Ok(f) = obj.cast::<PyFloat>() {
        return Ok(Value::Float(f.value()));
    }
    if let Ok(s) = obj.cast::<PyString>() {
        return Ok(Value::Str(s.to_str()?.to_string()));
    }
    if obj.is_instance_of::<PyList>() || obj.is_instance_of::<PyTuple>() {
        let mut items = Vec::new();
        for (i, item) in obj.try_iter()?.enumerate() {
            items.push(py_to_value(&item?, &child(path, &i.to_string()), depth + 1)?);
        }
        return Ok(Value::Array(items));
    }
    if let Ok(d) = obj.cast::<PyDict>() {
        let mut entries = Vec::with_capacity(d.len());
        for (k, v) in d.iter() {
            let Ok(key) = k.cast::<PyString>() else {
                return Err(PyTypeError::new_err(format!(
                    "dict keys must be str, got {} at {}",
                    type_name(&k),
                    location(path)
                )));
            };
            let key = key.to_str()?.to_string();
            let value = py_to_value(&v, &child(path, &key), depth + 1)?;
            entries.push((key, value));
        }
        return Ok(Value::Object(entries));
    }
    Err(PyTypeError::new_err(format!(
        "unsupported type '{}' at {}; expected None, bool, int, float, str, list, tuple or dict",
        type_name(obj),
        location(path)
    )))
}

/// Converts a [`Value`] to Python objects. Object key order is preserved.
pub fn value_to_py<'py>(py: Python<'py>, v: &Value) -> PyResult<Bound<'py, PyAny>> {
    match v {
        Value::Null => Ok(py.None().into_bound(py)),
        Value::Bool(b) => b.into_bound_py_any(py),
        Value::Int(i) => i.into_bound_py_any(py),
        Value::BigInt(s) => py.get_type::<PyInt>().call1((s.as_str(),)),
        Value::Float(f) => Ok(PyFloat::new(py, *f).into_any()),
        Value::Str(s) => Ok(PyString::new(py, s).into_any()),
        Value::Array(items) => {
            let list = PyList::empty(py);
            for item in items {
                list.append(value_to_py(py, item)?)?;
            }
            Ok(list.into_any())
        }
        Value::Object(entries) => {
            let dict = PyDict::new(py);
            for (k, item) in entries {
                dict.set_item(k, value_to_py(py, item)?)?;
            }
            Ok(dict.into_any())
        }
    }
}

/// Feeds the canonical encoding of a Python value into `h`.
pub fn hash_py(obj: &Bound<'_, PyAny>, h: &mut CanonicalHasher, path: &str, depth: usize) -> PyResult<()> {
    if depth > MAX_DEPTH {
        return Err(depth_error(path));
    }
    if obj.is_none() {
        h.null();
    } else if let Ok(b) = obj.cast::<PyBool>() {
        h.boolean(b.is_true());
    } else if obj.is_instance_of::<PyInt>() {
        match int_decimal(obj)? {
            Some(i) => h.int(i),
            None => h.int_decimal(obj.str()?.to_str()?),
        }
    } else if let Ok(f) = obj.cast::<PyFloat>() {
        h.float(f.value());
    } else if let Ok(s) = obj.cast::<PyString>() {
        h.string(s.to_str()?);
    } else if let Ok(b) = obj.cast::<PyBytes>() {
        h.bytes(b.as_bytes());
    } else if obj.is_instance_of::<PyList>() || obj.is_instance_of::<PyTuple>() {
        let items: Vec<Bound<'_, PyAny>> = obj.try_iter()?.collect::<PyResult<_>>()?;
        h.begin_list(items.len());
        for (i, item) in items.iter().enumerate() {
            hash_py(item, h, &child(path, &i.to_string()), depth + 1)?;
        }
    } else if let Ok(d) = obj.cast::<PyDict>() {
        let mut entries: Vec<(String, Bound<'_, PyAny>)> = Vec::with_capacity(d.len());
        for (k, v) in d.iter() {
            let Ok(key) = k.cast::<PyString>() else {
                return Err(PyTypeError::new_err(format!(
                    "dict keys must be str, got {} at {}",
                    type_name(&k),
                    location(path)
                )));
            };
            entries.push((key.to_str()?.to_string(), v));
        }
        entries.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        h.begin_map(entries.len());
        for (k, v) in &entries {
            h.string(k);
            hash_py(v, h, &child(path, k), depth + 1)?;
        }
    } else {
        return Err(PyTypeError::new_err(format!(
            "cannot hash type '{}' at {}; expected None, bool, int, float, str, bytes, list, tuple or dict",
            type_name(obj),
            location(path)
        )));
    }
    Ok(())
}

/// Stringifies a template variable value.
pub fn template_value(name: &str, obj: &Bound<'_, PyAny>) -> PyResult<String> {
    if let Ok(s) = obj.cast::<PyString>() {
        return Ok(s.to_str()?.to_string());
    }
    if obj.is_instance_of::<PyBool>() || obj.is_instance_of::<PyInt>() || obj.is_instance_of::<PyFloat>() {
        return Ok(obj.str()?.to_str()?.to_string());
    }
    Err(PyTypeError::new_err(format!(
        "template variable '{name}' has unsupported type '{}'; pass str, int, float or bool \
         (serialize other values explicitly, e.g. with json.dumps)",
        type_name(obj)
    )))
}

fn exception_class(kind: ErrorKind) -> Option<&'static str> {
    Some(match kind {
        ErrorKind::Malformed => "MalformedOutputError",
        ErrorKind::NoJsonFound => "NoJSONFoundError",
        ErrorKind::NoToolCallFound => "NoToolCallFoundError",
        ErrorKind::TemplateSyntax => "TemplateSyntaxError",
        ErrorKind::MissingVariable => "MissingVariableError",
        ErrorKind::ExtraVariable => "ExtraVariableError",
        ErrorKind::Schema => "SchemaError",
        ErrorKind::InvalidArgument | ErrorKind::InvalidType => return None,
    })
}

fn build_error(py: Python<'_>, err: &BlockError) -> PyResult<PyErr> {
    let Some(class_name) = exception_class(err.kind) else {
        return Ok(match err.kind {
            ErrorKind::InvalidType => PyTypeError::new_err(err.message.clone()),
            _ => PyValueError::new_err(err.message.clone()),
        });
    };
    let class = py.import("beacon.errors")?.getattr(class_name)?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("code", err.code)?;
    if let Some(pos) = err.position {
        kwargs.set_item("position", pos.offset)?;
        kwargs.set_item("line", pos.line)?;
        kwargs.set_item("column", pos.column)?;
    }
    if matches!(err.kind, ErrorKind::MissingVariable | ErrorKind::ExtraVariable) {
        kwargs.set_item("names", PyTuple::new(py, &err.names)?)?;
    }
    let instance = class.call((err.message.as_str(),), Some(&kwargs))?;
    Ok(PyErr::from_value(instance))
}

/// Converts a [`BlockError`] into the matching Python exception.
pub fn to_py_err(py: Python<'_>, err: BlockError) -> PyErr {
    build_error(py, &err).unwrap_or_else(|e| {
        PyRuntimeError::new_err(format!("beacon: could not raise {:?} ({}): {e}", err.kind, err.message))
    })
}

/// Validation errors as a list of `{"path", "keyword", "message"}` dicts.
pub fn errors_to_py<'py>(py: Python<'py>, errors: &[ValidationError]) -> PyResult<Bound<'py, PyList>> {
    let list = PyList::empty(py);
    for e in errors {
        let d = PyDict::new(py);
        d.set_item("path", &e.path)?;
        d.set_item("keyword", e.keyword)?;
        d.set_item("message", &e.message)?;
        list.append(d)?;
    }
    Ok(list)
}

/// Raises `SchemaValidationError` for a non-empty error list.
pub fn schema_validation_err(py: Python<'_>, errors: &[ValidationError]) -> PyErr {
    let build = || -> PyResult<PyErr> {
        let class = py.import("beacon.errors")?.getattr("SchemaValidationError")?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("errors", errors_to_py(py, errors)?)?;
        kwargs.set_item("code", "schema.validation_failed")?;
        let message = crate::validate_schema::format_errors(errors);
        Ok(PyErr::from_value(class.call((message,), Some(&kwargs))?))
    };
    build().unwrap_or_else(|e| PyRuntimeError::new_err(format!("beacon: could not raise SchemaValidationError: {e}")))
}
