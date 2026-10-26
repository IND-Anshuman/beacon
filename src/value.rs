//! An ordered, lossless JSON value.
//!
//! Objects keep their keys in insertion order (a `Vec` of pairs, not a hash
//! map), so iteration order is a property of the input and never of a hasher.
//! Integers that do not fit in an `i64` are kept as their exact decimal text.

use std::cmp::Ordering;
use std::fmt::Write as _;

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    /// An integer outside the `i64` range, as canonical decimal text
    /// (optional `-`, no leading zeros).
    BigInt(String),
    Float(f64),
    Str(String),
    Array(Vec<Value>),
    Object(Vec<(String, Value)>),
}

impl Value {
    /// The JSON Schema type name of this value. Floats are `"number"`, even
    /// when they have no fractional part.
    pub fn type_name(&self) -> &'static str {
        match self {
            Value::Null => "null",
            Value::Bool(_) => "boolean",
            Value::Int(_) | Value::BigInt(_) => "integer",
            Value::Float(_) => "number",
            Value::Str(_) => "string",
            Value::Array(_) => "array",
            Value::Object(_) => "object",
        }
    }

    pub fn is_number(&self) -> bool {
        matches!(self, Value::Int(_) | Value::BigInt(_) | Value::Float(_))
    }

    /// Looks up a key in an object. Returns `None` for non-objects.
    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Object(entries) => entries.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    /// The value as an `f64`, for numbers only. Big integers are converted
    /// with correct rounding.
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Value::Int(i) => Some(*i as f64),
            Value::BigInt(s) => s.parse::<f64>().ok(),
            Value::Float(f) => Some(*f),
            _ => None,
        }
    }

    /// Compact JSON text, used in error messages. Keys keep their order.
    pub fn to_json(&self) -> String {
        let mut out = String::new();
        self.write_json(&mut out);
        out
    }

    fn write_json(&self, out: &mut String) {
        match self {
            Value::Null => out.push_str("null"),
            Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Value::Int(i) => {
                let _ = write!(out, "{i}");
            }
            Value::BigInt(s) => out.push_str(s),
            Value::Float(f) => out.push_str(&format_float(*f)),
            Value::Str(s) => write_json_string(s, out),
            Value::Array(items) => {
                out.push('[');
                for (i, item) in items.iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    item.write_json(out);
                }
                out.push(']');
            }
            Value::Object(entries) => {
                out.push('{');
                for (i, (k, v)) in entries.iter().enumerate() {
                    if i > 0 {
                        out.push_str(", ");
                    }
                    write_json_string(k, out);
                    out.push_str(": ");
                    v.write_json(out);
                }
                out.push('}');
            }
        }
    }
}

/// Formats a float the way Python's `repr` does for the common cases:
/// shortest round-trip digits, always with a `.` or exponent.
pub fn format_float(f: f64) -> String {
    if f.is_nan() {
        return "NaN".to_string();
    }
    if f.is_infinite() {
        return if f > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }
    // `{:?}` prints the shortest representation that round-trips and always
    // includes a `.0` or an exponent.
    format!("{f:?}")
}

/// Writes `s` as a JSON string literal (with quotes). Non-ASCII characters
/// are written as-is; control characters are escaped.
pub fn write_json_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0C}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 || c == '\u{7F}' => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// Compares two numbers exactly where possible. Returns `None` if either is
/// not a number or a NaN is involved.
pub fn compare_numbers(a: &Value, b: &Value) -> Option<Ordering> {
    match (a, b) {
        (Value::Int(x), Value::Int(y)) => Some(x.cmp(y)),
        (Value::Int(x), Value::Float(y)) => compare_int_float(*x, *y),
        (Value::Float(x), Value::Int(y)) => compare_int_float(*y, *x).map(Ordering::reverse),
        (Value::Float(x), Value::Float(y)) => x.partial_cmp(y),
        (Value::BigInt(x), Value::BigInt(y)) => Some(compare_decimal_ints(x, y)),
        (Value::BigInt(x), Value::Int(y)) => Some(compare_decimal_ints(x, &y.to_string())),
        (Value::Int(x), Value::BigInt(y)) => Some(compare_decimal_ints(&x.to_string(), y)),
        _ => a.as_f64()?.partial_cmp(&b.as_f64()?),
    }
}

/// Exact comparison of an integer and a float.
fn compare_int_float(i: i64, f: f64) -> Option<Ordering> {
    if f.is_nan() {
        return None;
    }
    // 2^63 as f64 is exact; anything at or above it is larger than any i64.
    const TWO_63: f64 = 9_223_372_036_854_775_808.0;
    if f >= TWO_63 {
        return Some(Ordering::Less);
    }
    if f < -TWO_63 {
        return Some(Ordering::Greater);
    }
    let t = f.trunc();
    // `t` is integral and within i64 range here, so the cast is exact.
    let ti = t as i64;
    match i.cmp(&ti) {
        Ordering::Equal => {
            if f > t {
                Some(Ordering::Less)
            } else if f < t {
                Some(Ordering::Greater)
            } else {
                Some(Ordering::Equal)
            }
        }
        other => Some(other),
    }
}

/// Compares two canonical decimal integer strings.
fn compare_decimal_ints(a: &str, b: &str) -> Ordering {
    let (an, ad) = a.strip_prefix('-').map_or((false, a), |d| (true, d));
    let (bn, bd) = b.strip_prefix('-').map_or((false, b), |d| (true, d));
    let mag = ad.len().cmp(&bd.len()).then_with(|| ad.cmp(bd));
    match (an, bn) {
        (false, false) => mag,
        (true, true) => mag.reverse(),
        (true, false) => {
            if ad == "0" && bd == "0" {
                Ordering::Equal
            } else {
                Ordering::Less
            }
        }
        (false, true) => {
            if ad == "0" && bd == "0" {
                Ordering::Equal
            } else {
                Ordering::Greater
            }
        }
    }
}

/// JSON equality as defined by JSON Schema: numbers compare by value
/// (`1 == 1.0`), objects compare as unordered key sets, arrays element-wise.
pub fn json_equal(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Null, Value::Null) => true,
        (Value::Bool(x), Value::Bool(y)) => x == y,
        (Value::Str(x), Value::Str(y)) => x == y,
        (x, y) if x.is_number() && y.is_number() => compare_numbers(x, y) == Some(Ordering::Equal),
        (Value::Array(x), Value::Array(y)) => x.len() == y.len() && x.iter().zip(y).all(|(p, q)| json_equal(p, q)),
        (Value::Object(x), Value::Object(y)) => {
            x.len() == y.len() && x.iter().all(|(k, v)| b.get(k).is_some_and(|w| json_equal(v, w)))
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn numbers_compare_across_representations() {
        assert!(json_equal(&Value::Int(1), &Value::Float(1.0)));
        assert!(!json_equal(&Value::Int(1), &Value::Float(1.5)));
        assert!(!json_equal(&Value::Int(1), &Value::Bool(true)));
        assert_eq!(compare_numbers(&Value::Int(i64::MAX), &Value::Float(9.3e18)), Some(Ordering::Less));
        assert_eq!(
            compare_numbers(&Value::BigInt("-99999999999999999999".into()), &Value::Int(0)),
            Some(Ordering::Less)
        );
        assert_eq!(compare_numbers(&Value::Int(3), &Value::Float(2.5)), Some(Ordering::Greater));
        assert_eq!(compare_numbers(&Value::Float(f64::NAN), &Value::Int(1)), None);
    }

    #[test]
    fn object_equality_ignores_order() {
        let a = Value::Object(vec![("a".into(), Value::Int(1)), ("b".into(), Value::Int(2))]);
        let b = Value::Object(vec![("b".into(), Value::Int(2)), ("a".into(), Value::Int(1))]);
        assert!(json_equal(&a, &b));
    }

    #[test]
    fn to_json_is_compact_and_ordered() {
        let v = Value::Object(vec![
            ("z".into(), Value::Array(vec![Value::Float(0.5), Value::Null])),
            ("a".into(), Value::Str("q\"\n".into())),
        ]);
        assert_eq!(v.to_json(), r#"{"z": [0.5, null], "a": "q\"\n"}"#);
        assert_eq!(format_float(1.0), "1.0");
        assert_eq!(format_float(1e21), "1e21");
    }
}
