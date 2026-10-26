//! JSON Schema validation for the subset of JSON Schema (2020-12) that LLM
//! applications use, including everything Pydantic's `model_json_schema()`
//! emits.
//!
//! Two passes:
//!
//! 1. **Schema check** — the whole schema is walked once. Unknown keywords,
//!    keyword values of the wrong type, invalid regexes and unresolvable
//!    `$ref`s raise `SchemaError` *before* the instance is looked at, so a bad
//!    schema fails the same way for every instance.
//! 2. **Validation** — strict, never coercing (`"42"` is not a number). All
//!    errors are collected in a fixed order:
//!    `$ref` → `type` (stops this node on failure) → `enum`/`const` →
//!    string / number / array / object keywords → `allOf`, `anyOf`, `oneOf`,
//!    `not`, `if`/`then`/`else`. Object members are visited in the instance's
//!    key order; array items in index order.

use std::collections::HashMap;
use std::fmt::Write as _;

use regex::Regex;

use crate::error::{BlockError, ErrorKind};
use crate::value::{Value, compare_numbers, json_equal};

/// Maximum combined depth of schema nesting, `$ref` hops and instance nesting.
pub const MAX_DEPTH: usize = 256;

/// One validation failure. `path` is a JSON Pointer into the instance
/// (`""` is the root).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidationError {
    pub path: String,
    pub keyword: &'static str,
    pub message: String,
}

const TYPES: [&str; 7] = ["null", "boolean", "integer", "number", "string", "array", "object"];

/// Keywords that never affect validation.
const ANNOTATIONS: [&str; 17] = [
    "$schema",
    "$id",
    "$comment",
    "$anchor",
    "title",
    "description",
    "default",
    "examples",
    "deprecated",
    "readOnly",
    "writeOnly",
    "format",
    "contentEncoding",
    "contentMediaType",
    "contentSchema",
    "discriminator",
    "$vocabulary",
];

const KEYWORDS: [&str; 37] = [
    "$ref",
    "$defs",
    "definitions",
    "type",
    "enum",
    "const",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "uniqueItems",
    "prefixItems",
    "items",
    "contains",
    "minContains",
    "maxContains",
    "required",
    "dependentRequired",
    "minProperties",
    "maxProperties",
    "propertyNames",
    "properties",
    "patternProperties",
    "additionalProperties",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
];

fn schema_err(message: String) -> BlockError {
    BlockError::new(ErrorKind::Schema, "schema.invalid", message)
}

fn push_pointer(base: &str, token: &str) -> String {
    let mut s = String::with_capacity(base.len() + token.len() + 1);
    s.push_str(base);
    s.push('/');
    for c in token.chars() {
        match c {
            '~' => s.push_str("~0"),
            '/' => s.push_str("~1"),
            c => s.push(c),
        }
    }
    s
}

fn quote(s: &str) -> String {
    let mut out = String::new();
    crate::value::write_json_string(s, &mut out);
    out
}

/// JSON text of a value, cut to 80 characters for error messages.
fn shown(v: &Value) -> String {
    let json = v.to_json();
    if json.chars().count() <= 80 {
        json
    } else {
        let mut cut: String = json.chars().take(79).collect();
        cut.push('…');
        cut
    }
}

fn as_count(v: &Value) -> Option<u64> {
    match v {
        Value::Int(i) if *i >= 0 => Some(*i as u64),
        Value::Float(f) if *f >= 0.0 && f.fract() == 0.0 && *f < 1.8e19 => Some(*f as u64),
        _ => None,
    }
}

fn is_integer(v: &Value) -> bool {
    match v {
        Value::Int(_) | Value::BigInt(_) => true,
        Value::Float(f) => f.is_finite() && f.fract() == 0.0,
        _ => false,
    }
}

fn matches_type(v: &Value, t: &str) -> bool {
    match t {
        "null" => matches!(v, Value::Null),
        "boolean" => matches!(v, Value::Bool(_)),
        "integer" => is_integer(v),
        "number" => v.is_number(),
        "string" => matches!(v, Value::Str(_)),
        "array" => matches!(v, Value::Array(_)),
        "object" => matches!(v, Value::Object(_)),
        _ => false,
    }
}

/// Resolves a local `$ref` against the root schema.
fn resolve_ref<'s>(root: &'s Value, reference: &str) -> Result<&'s Value, BlockError> {
    let Some(pointer) = reference.strip_prefix('#') else {
        return Err(schema_err(format!(
            "unsupported $ref {}: only local references ('#' or '#/...') are supported",
            quote(reference)
        )));
    };
    if pointer.is_empty() {
        return Ok(root);
    }
    let Some(rest) = pointer.strip_prefix('/') else {
        return Err(schema_err(format!(
            "unsupported $ref {}: only local references ('#' or '#/...') are supported",
            quote(reference)
        )));
    };
    let mut node = root;
    for raw in rest.split('/') {
        let token = raw.replace("~1", "/").replace("~0", "~");
        node = match node {
            Value::Object(_) => node.get(&token),
            Value::Array(items) => token.parse::<usize>().ok().and_then(|i| items.get(i)),
            _ => None,
        }
        .ok_or_else(|| schema_err(format!("unresolvable $ref {}", quote(reference))))?;
    }
    Ok(node)
}

struct Validator<'s> {
    root: &'s Value,
    regexes: HashMap<String, Regex>,
    errors: Vec<ValidationError>,
}

impl<'s> Validator<'s> {
    fn compile(&mut self, pattern: &str, keyword: &str, loc: &str) -> Result<(), BlockError> {
        if self.regexes.contains_key(pattern) {
            return Ok(());
        }
        match Regex::new(pattern) {
            Ok(re) => {
                self.regexes.insert(pattern.to_string(), re);
                Ok(())
            }
            Err(_) => Err(schema_err(format!(
                "invalid or unsupported regular expression {} in '{keyword}' at '{loc}' \
                 (beacon uses Rust regex syntax: no look-around or backreferences)",
                quote(pattern)
            ))),
        }
    }

    fn is_match(&self, pattern: &str, s: &str) -> bool {
        self.regexes.get(pattern).is_some_and(|re| re.is_match(s))
    }

    // ---------------------------------------------------------------- pass 1

    fn check_schema(&mut self, schema: &'s Value, loc: &str, depth: usize) -> Result<(), BlockError> {
        if depth > MAX_DEPTH {
            return Err(schema_err(format!("schema nesting is deeper than {MAX_DEPTH} levels")));
        }
        let entries = match schema {
            Value::Bool(_) => return Ok(()),
            Value::Object(entries) => entries,
            _ => {
                return Err(schema_err(format!(
                    "schema at '{loc}' must be an object or a boolean, got {}",
                    schema.type_name()
                )));
            }
        };
        for (key, value) in entries {
            let here = push_pointer(loc, key);
            if ANNOTATIONS.contains(&key.as_str()) {
                continue;
            }
            if !KEYWORDS.contains(&key.as_str()) {
                return Err(schema_err(format!("unsupported schema keyword {} at '{loc}'", quote(key))));
            }
            let bad = |expected: &str| {
                schema_err(format!("invalid value for {} at '{loc}': expected {expected}", quote(key)))
            };
            match key.as_str() {
                "$ref" => {
                    let r = value.as_str().ok_or_else(|| bad("a string"))?;
                    resolve_ref(self.root, r)?;
                }
                "$defs" | "definitions" | "properties" | "patternProperties" => {
                    let Value::Object(members) = value else {
                        return Err(bad("an object"));
                    };
                    for (name, sub) in members {
                        if key == "patternProperties" {
                            self.compile(name, key, loc)?;
                        }
                        self.check_schema(sub, &push_pointer(&here, name), depth + 1)?;
                    }
                }
                "type" => {
                    let ok = match value {
                        Value::Str(t) => TYPES.contains(&t.as_str()),
                        Value::Array(ts) => {
                            !ts.is_empty()
                                && ts.iter().all(|t| t.as_str().is_some_and(|t| TYPES.contains(&t)))
                                && ts.iter().enumerate().all(|(i, t)| !ts[..i].contains(t))
                        }
                        _ => false,
                    };
                    if !ok {
                        return Err(bad("a type name or a non-empty array of unique type names \
                             (null, boolean, integer, number, string, array, object)"));
                    }
                }
                "enum" => {
                    if !matches!(value, Value::Array(_)) {
                        return Err(bad("an array"));
                    }
                }
                "const" => {}
                "minLength" | "maxLength" | "minItems" | "maxItems" | "minProperties" | "maxProperties"
                | "minContains" | "maxContains" => {
                    as_count(value).ok_or_else(|| bad("a non-negative integer"))?;
                }
                "pattern" => {
                    let p = value.as_str().ok_or_else(|| bad("a string"))?;
                    self.compile(p, key, loc)?;
                }
                "minimum" | "maximum" | "exclusiveMinimum" | "exclusiveMaximum" => {
                    if !value.is_number() {
                        return Err(bad("a number"));
                    }
                }
                "multipleOf" => {
                    if !value.as_f64().is_some_and(|f| f > 0.0) {
                        return Err(bad("a number greater than 0"));
                    }
                }
                "uniqueItems" => {
                    if !matches!(value, Value::Bool(_)) {
                        return Err(bad("a boolean"));
                    }
                }
                "required" => {
                    let Value::Array(names) = value else {
                        return Err(bad("an array of strings"));
                    };
                    if !names.iter().all(|n| matches!(n, Value::Str(_))) {
                        return Err(bad("an array of strings"));
                    }
                }
                "dependentRequired" => {
                    let Value::Object(members) = value else {
                        return Err(bad("an object of string arrays"));
                    };
                    for (_, deps) in members {
                        match deps {
                            Value::Array(ns) if ns.iter().all(|n| matches!(n, Value::Str(_))) => {}
                            _ => return Err(bad("an object of string arrays")),
                        }
                    }
                }
                "items" => {
                    if matches!(value, Value::Array(_)) {
                        return Err(schema_err(format!(
                            "the array form of \"items\" at '{loc}' is not supported; use \"prefixItems\""
                        )));
                    }
                    self.check_schema(value, &here, depth + 1)?;
                }
                "prefixItems" | "allOf" | "anyOf" | "oneOf" => {
                    let Value::Array(subs) = value else {
                        return Err(bad("a non-empty array of schemas"));
                    };
                    if subs.is_empty() {
                        return Err(bad("a non-empty array of schemas"));
                    }
                    for (i, sub) in subs.iter().enumerate() {
                        self.check_schema(sub, &push_pointer(&here, &i.to_string()), depth + 1)?;
                    }
                }
                // Single subschemas.
                _ => self.check_schema(value, &here, depth + 1)?,
            }
        }
        Ok(())
    }

    // ---------------------------------------------------------------- pass 2

    fn error(&mut self, path: &str, keyword: &'static str, message: String) {
        self.errors.push(ValidationError { path: path.to_string(), keyword, message });
    }

    /// Validates into a fresh error list and returns it, leaving `self.errors`
    /// untouched.
    fn collect(
        &mut self,
        inst: &Value,
        schema: &'s Value,
        path: &str,
        depth: usize,
    ) -> Result<Vec<ValidationError>, BlockError> {
        let saved = std::mem::take(&mut self.errors);
        let result = self.validate(inst, schema, path, depth);
        let produced = std::mem::replace(&mut self.errors, saved);
        result.map(|()| produced)
    }

    fn validate(&mut self, inst: &Value, schema: &'s Value, path: &str, depth: usize) -> Result<(), BlockError> {
        if depth > MAX_DEPTH {
            return Err(schema_err(format!("validation depth limit ({MAX_DEPTH}) exceeded; check for a cyclic $ref")));
        }
        let s = match schema {
            Value::Bool(true) => return Ok(()),
            Value::Bool(false) => {
                self.error(path, "false", "no value is allowed here".to_string());
                return Ok(());
            }
            Value::Object(_) => schema,
            _ => return Err(schema_err("schema must be an object or a boolean".to_string())),
        };

        if let Some(Value::Str(r)) = s.get("$ref") {
            let target = resolve_ref(self.root, r)?;
            self.validate(inst, target, path, depth + 1)?;
        }

        if let Some(t) = s.get("type") {
            let ok = match t {
                Value::Str(name) => matches_type(inst, name),
                Value::Array(names) => names.iter().any(|n| n.as_str().is_some_and(|n| matches_type(inst, n))),
                _ => true,
            };
            if !ok {
                let expected = match t {
                    Value::Str(name) => format!("expected type {}", quote(name)),
                    Value::Array(names) => {
                        let list: Vec<String> = names.iter().filter_map(Value::as_str).map(quote).collect();
                        format!("expected one of types {}", list.join(", "))
                    }
                    _ => String::new(),
                };
                self.error(path, "type", format!("{expected}, got {}", quote(inst.type_name())));
                return Ok(());
            }
        }

        if let Some(Value::Array(allowed)) = s.get("enum") {
            if !allowed.iter().any(|a| json_equal(a, inst)) {
                self.error(
                    path,
                    "enum",
                    format!("{} is not one of {}", shown(inst), shown(&Value::Array(allowed.clone()))),
                );
            }
        }
        if let Some(c) = s.get("const") {
            if !json_equal(c, inst) {
                self.error(path, "const", format!("{} is not equal to the constant {}", shown(inst), shown(c)));
            }
        }

        match inst {
            Value::Str(text) => self.validate_string(text, s, path),
            Value::Int(_) | Value::BigInt(_) | Value::Float(_) => self.validate_number(inst, s, path),
            Value::Array(items) => self.validate_array(items, s, path, depth)?,
            Value::Object(entries) => self.validate_object(entries, s, path, depth)?,
            Value::Null | Value::Bool(_) => {}
        }

        self.validate_combinators(inst, s, path, depth)
    }

    fn validate_string(&mut self, text: &str, s: &Value, path: &str) {
        let len = text.chars().count() as u64;
        if let Some(min) = s.get("minLength").and_then(as_count) {
            if len < min {
                self.error(path, "minLength", format!("string has {len} characters, fewer than the minimum of {min}"));
            }
        }
        if let Some(max) = s.get("maxLength").and_then(as_count) {
            if len > max {
                self.error(path, "maxLength", format!("string has {len} characters, more than the maximum of {max}"));
            }
        }
        if let Some(Value::Str(p)) = s.get("pattern") {
            if !self.is_match(p, text) {
                self.error(path, "pattern", format!("string does not match the pattern {}", quote(p)));
            }
        }
    }

    fn validate_number(&mut self, inst: &Value, s: &Value, path: &str) {
        use std::cmp::Ordering::{Equal, Greater, Less};
        let v = inst.to_json();
        let checks: [(&'static str, &[std::cmp::Ordering], &str); 4] = [
            ("minimum", &[Less], "is less than the minimum of"),
            ("exclusiveMinimum", &[Less, Equal], "is less than or equal to the exclusive minimum of"),
            ("maximum", &[Greater], "is greater than the maximum of"),
            ("exclusiveMaximum", &[Greater, Equal], "is greater than or equal to the exclusive maximum of"),
        ];
        for (keyword, failing, phrase) in checks {
            if let Some(bound) = s.get(keyword).filter(|b| b.is_number()) {
                if compare_numbers(inst, bound).is_some_and(|o| failing.contains(&o)) {
                    self.error(path, keyword, format!("{v} {phrase} {}", bound.to_json()));
                }
            }
        }
        if let Some(m) = s.get("multipleOf").filter(|m| m.is_number()) {
            if !is_multiple_of(inst, m) {
                self.error(path, "multipleOf", format!("{v} is not a multiple of {}", m.to_json()));
            }
        }
    }

    fn validate_array(&mut self, items: &[Value], s: &'s Value, path: &str, depth: usize) -> Result<(), BlockError> {
        let n = items.len() as u64;
        if let Some(min) = s.get("minItems").and_then(as_count) {
            if n < min {
                self.error(path, "minItems", format!("array has {n} items, fewer than the minimum of {min}"));
            }
        }
        if let Some(max) = s.get("maxItems").and_then(as_count) {
            if n > max {
                self.error(path, "maxItems", format!("array has {n} items, more than the maximum of {max}"));
            }
        }
        if let Some(Value::Bool(true)) = s.get("uniqueItems") {
            'outer: for i in 0..items.len() {
                for j in i + 1..items.len() {
                    if json_equal(&items[i], &items[j]) {
                        self.error(path, "uniqueItems", format!("array items {i} and {j} are equal"));
                        break 'outer;
                    }
                }
            }
        }
        let mut prefix_len = 0;
        if let Some(Value::Array(prefix)) = s.get("prefixItems") {
            prefix_len = prefix.len();
            for (i, (item, sub)) in items.iter().zip(prefix).enumerate() {
                self.validate(item, sub, &push_pointer(path, &i.to_string()), depth + 1)?;
            }
        }
        if let Some(sub) = s.get("items") {
            if matches!(sub, Value::Bool(false)) {
                if items.len() > prefix_len {
                    self.error(path, "items", format!("array has {n} items, but only {prefix_len} are allowed"));
                }
            } else {
                for (i, item) in items.iter().enumerate().skip(prefix_len) {
                    self.validate(item, sub, &push_pointer(path, &i.to_string()), depth + 1)?;
                }
            }
        }
        if let Some(sub) = s.get("contains") {
            let mut matching = 0u64;
            for (i, item) in items.iter().enumerate() {
                if self.collect(item, sub, &push_pointer(path, &i.to_string()), depth + 1)?.is_empty() {
                    matching += 1;
                }
            }
            let min = s.get("minContains").and_then(as_count).unwrap_or(1);
            if matching < min {
                if min == 1 {
                    self.error(path, "contains", "array has no item matching 'contains'".to_string());
                } else {
                    self.error(
                        path,
                        "minContains",
                        format!("array has {matching} items matching 'contains', fewer than the minimum of {min}"),
                    );
                }
            }
            if let Some(max) = s.get("maxContains").and_then(as_count) {
                if matching > max {
                    self.error(
                        path,
                        "maxContains",
                        format!("array has {matching} items matching 'contains', more than the maximum of {max}"),
                    );
                }
            }
        }
        Ok(())
    }

    fn validate_object(
        &mut self,
        entries: &[(String, Value)],
        s: &'s Value,
        path: &str,
        depth: usize,
    ) -> Result<(), BlockError> {
        let has = |k: &str| entries.iter().any(|(e, _)| e == k);
        if let Some(Value::Array(required)) = s.get("required") {
            for name in required.iter().filter_map(Value::as_str) {
                if !has(name) {
                    self.error(path, "required", format!("missing required property {}", quote(name)));
                }
            }
        }
        if let Some(Value::Object(deps)) = s.get("dependentRequired") {
            for (name, needed) in deps {
                if !has(name) {
                    continue;
                }
                if let Value::Array(needed) = needed {
                    for other in needed.iter().filter_map(Value::as_str) {
                        if !has(other) {
                            self.error(
                                path,
                                "dependentRequired",
                                format!("property {} requires property {}", quote(name), quote(other)),
                            );
                        }
                    }
                }
            }
        }
        let n = entries.len() as u64;
        if let Some(min) = s.get("minProperties").and_then(as_count) {
            if n < min {
                self.error(
                    path,
                    "minProperties",
                    format!("object has {n} properties, fewer than the minimum of {min}"),
                );
            }
        }
        if let Some(max) = s.get("maxProperties").and_then(as_count) {
            if n > max {
                self.error(path, "maxProperties", format!("object has {n} properties, more than the maximum of {max}"));
            }
        }
        if let Some(names_schema) = s.get("propertyNames") {
            for (key, _) in entries {
                let errs = self.collect(&Value::Str(key.clone()), names_schema, path, depth + 1)?;
                if let Some(first) = errs.first() {
                    self.error(
                        path,
                        "propertyNames",
                        format!("property name {} is invalid: {}", quote(key), first.message),
                    );
                }
            }
        }

        let properties = match s.get("properties") {
            Some(Value::Object(p)) => Some(p),
            _ => None,
        };
        let patterns = match s.get("patternProperties") {
            Some(Value::Object(p)) => Some(p),
            _ => None,
        };
        let additional = s.get("additionalProperties");
        for (key, value) in entries {
            let child = push_pointer(path, key);
            let mut evaluated = false;
            if let Some(sub) = properties.and_then(|p| p.iter().find(|(k, _)| k == key)).map(|(_, v)| v) {
                evaluated = true;
                self.validate(value, sub, &child, depth + 1)?;
            }
            if let Some(patterns) = patterns {
                for (pattern, sub) in patterns {
                    if self.is_match(pattern, key) {
                        evaluated = true;
                        self.validate(value, sub, &child, depth + 1)?;
                    }
                }
            }
            if !evaluated {
                match additional {
                    Some(Value::Bool(false)) => {
                        self.error(
                            path,
                            "additionalProperties",
                            format!("additional property {} is not allowed", quote(key)),
                        );
                    }
                    Some(sub) => self.validate(value, sub, &child, depth + 1)?,
                    None => {}
                }
            }
        }
        Ok(())
    }

    fn validate_combinators(&mut self, inst: &Value, s: &'s Value, path: &str, depth: usize) -> Result<(), BlockError> {
        if let Some(Value::Array(subs)) = s.get("allOf") {
            for sub in subs {
                self.validate(inst, sub, path, depth + 1)?;
            }
        }
        if let Some(Value::Array(subs)) = s.get("anyOf") {
            let mut branches = Vec::with_capacity(subs.len());
            for sub in subs {
                let errs = self.collect(inst, sub, path, depth + 1)?;
                if errs.is_empty() {
                    branches.clear();
                    break;
                }
                branches.push(errs);
            }
            if !branches.is_empty() {
                self.report_union(path, "anyOf", branches);
            }
        }
        if let Some(Value::Array(subs)) = s.get("oneOf") {
            let mut passing = Vec::new();
            let mut branches = Vec::with_capacity(subs.len());
            for (i, sub) in subs.iter().enumerate() {
                let errs = self.collect(inst, sub, path, depth + 1)?;
                if errs.is_empty() {
                    passing.push(i);
                } else {
                    branches.push(errs);
                }
            }
            match passing.as_slice() {
                [] => self.report_union(path, "oneOf", branches),
                [_] => {}
                [i, j, ..] => self.error(
                    path,
                    "oneOf",
                    format!("value matches more than one subschema in oneOf (indices {i} and {j})"),
                ),
            }
        }
        if let Some(sub) = s.get("not") {
            if self.collect(inst, sub, path, depth + 1)?.is_empty() {
                self.error(path, "not", "value must not match the 'not' schema".to_string());
            }
        }
        if let Some(cond) = s.get("if") {
            let branch =
                if self.collect(inst, cond, path, depth + 1)?.is_empty() { s.get("then") } else { s.get("else") };
            if let Some(sub) = branch {
                self.validate(inst, sub, path, depth + 1)?;
            }
        }
        Ok(())
    }

    /// Reports a failed `anyOf`/`oneOf`. If every branch but one failed on
    /// `type` at the value itself, the value was evidently meant for the
    /// remaining branch, so that branch's errors are reported. Otherwise one
    /// summary error is reported.
    fn report_union(&mut self, path: &str, keyword: &'static str, branches: Vec<Vec<ValidationError>>) {
        let type_mismatch =
            |errs: &Vec<ValidationError>| errs.len() == 1 && errs[0].keyword == "type" && errs[0].path == path;
        let candidates: Vec<&Vec<ValidationError>> = branches.iter().filter(|e| !type_mismatch(e)).collect();
        if let [only] = candidates.as_slice() {
            self.errors.extend(only.iter().cloned());
        } else {
            let n = branches.len();
            self.error(path, keyword, format!("value does not match any of the {n} subschemas in {keyword}"));
        }
    }
}

/// Decomposes a number into `(mantissa, exponent)` with `value = ±mantissa ×
/// 10^exponent`, using the shortest round-trip decimal form of floats.
fn to_decimal(v: &Value) -> Option<(u128, i32)> {
    let text = match v {
        Value::Int(i) => return Some((u128::from(i.unsigned_abs()), 0)),
        Value::BigInt(s) => return s.trim_start_matches('-').parse::<u128>().ok().map(|m| (m, 0)),
        Value::Float(f) if f.is_finite() => format!("{:e}", f.abs()),
        _ => return None,
    };
    let (mant, exp) = text.split_once('e')?;
    let exp: i32 = exp.parse().ok()?;
    let (int_part, frac_part) = mant.split_once('.').unwrap_or((mant, ""));
    let digits = format!("{int_part}{frac_part}");
    let mantissa = digits.parse::<u128>().ok()?;
    Some((mantissa, exp - frac_part.len() as i32))
}

fn is_multiple_of(v: &Value, m: &Value) -> bool {
    if let (Some((a, p)), Some((b, q))) = (to_decimal(v), to_decimal(m)) {
        if b == 0 {
            return false;
        }
        let k = p.min(q);
        let scale =
            |x: u128, e: i32| -> Option<u128> { 10u128.checked_pow((e - k) as u32).and_then(|f| x.checked_mul(f)) };
        if let (Some(aa), Some(bb)) = (scale(a, p), scale(b, q)) {
            return aa % bb == 0;
        }
    }
    match (v.as_f64(), m.as_f64()) {
        (Some(x), Some(y)) if y != 0.0 => {
            let r = x / y;
            r.is_finite() && r == r.trunc()
        }
        _ => false,
    }
}

/// Validates `instance` against `schema`, returning every violation in the
/// documented order. Returns `Err` only if the schema itself is invalid.
pub fn validate(instance: &Value, schema: &Value) -> Result<Vec<ValidationError>, BlockError> {
    let mut v = Validator { root: schema, regexes: HashMap::new(), errors: Vec::new() };
    v.check_schema(schema, "#", 0)?;
    v.validate(instance, schema, "", 0)?;
    Ok(v.errors)
}

/// Formats violations as the message of a `SchemaValidationError`.
pub fn format_errors(errors: &[ValidationError]) -> String {
    let mut out = String::new();
    let n = errors.len();
    let _ = write!(out, "{n} schema violation{}:", if n == 1 { "" } else { "s" });
    for e in errors {
        let where_ = if e.path.is_empty() { "(root)" } else { e.path.as_str() };
        let _ = write!(out, "\n  - {where_}: {}", e.message);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::parse_document;

    fn errs(instance: &str, schema: &str) -> Vec<(String, &'static str, String)> {
        let i = parse_document(instance).unwrap();
        let s = parse_document(schema).unwrap();
        validate(&i, &s).unwrap().into_iter().map(|e| (e.path, e.keyword, e.message)).collect()
    }

    const INTENT: &str = r#"{
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["cancel", "refund", "question"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        },
        "required": ["intent", "confidence"]
    }"#;

    #[test]
    fn valid_instance() {
        assert!(errs(r#"{"intent": "cancel", "confidence": 0.9}"#, INTENT).is_empty());
    }

    #[test]
    fn field_level_errors_in_instance_order() {
        let e = errs(r#"{"intent": "explode", "confidence": 1.5}"#, INTENT);
        assert_eq!(
            e,
            vec![
                (
                    "/intent".to_string(),
                    "enum",
                    r#""explode" is not one of ["cancel", "refund", "question"]"#.to_string()
                ),
                ("/confidence".to_string(), "maximum", "1.5 is greater than the maximum of 1".to_string()),
            ]
        );
    }

    #[test]
    fn no_coercion() {
        let e = errs(r#""42""#, r#"{"type": "number"}"#);
        assert_eq!(e[0].2, r#"expected type "number", got "string""#);
        assert!(errs("1.0", r#"{"type": "integer"}"#).is_empty());
        assert_eq!(errs("true", r#"{"type": "integer"}"#).len(), 1);
    }

    #[test]
    fn required_and_additional() {
        let e = errs(
            r#"{"a": 1, "extra": 2}"#,
            r#"{"type": "object", "properties": {"a": {}}, "required": ["a", "b"], "additionalProperties": false}"#,
        );
        assert_eq!(e[0].1, "required");
        assert_eq!(e[1].1, "additionalProperties");
    }

    #[test]
    fn refs_and_optional_unions() {
        let schema = r##"{
            "$defs": {"User": {"type": "object", "properties": {"age": {"type": "integer", "minimum": 0}}, "required": ["age"]}},
            "type": "object",
            "properties": {"user": {"anyOf": [{"$ref": "#/$defs/User"}, {"type": "null"}]}}
        }"##;
        assert!(errs(r#"{"user": null}"#, schema).is_empty());
        let e = errs(r#"{"user": {"age": -1}}"#, schema);
        assert_eq!(e, vec![("/user/age".to_string(), "minimum", "-1 is less than the minimum of 0".to_string())]);
        let e = errs(r#"{"user": "bob"}"#, schema);
        assert_eq!(e[0].1, "anyOf");
    }

    #[test]
    fn multiple_of_is_exact_for_decimals() {
        assert!(errs("0.3", r#"{"multipleOf": 0.1}"#).is_empty());
        assert!(errs("19.99", r#"{"multipleOf": 0.01}"#).is_empty());
        assert_eq!(errs("0.35", r#"{"multipleOf": 0.1}"#).len(), 1);
        assert!(errs("10", r#"{"multipleOf": 5}"#).is_empty());
    }

    #[test]
    fn schema_errors() {
        let check = |schema: &str| {
            let s = parse_document(schema).unwrap();
            validate(&Value::Null, &s).unwrap_err().kind
        };
        assert_eq!(check(r#"{"typo": 1}"#), ErrorKind::Schema);
        assert_eq!(check(r#"{"minimum": "0"}"#), ErrorKind::Schema);
        assert_eq!(check(r#"{"pattern": "(?=x)"}"#), ErrorKind::Schema);
        assert_eq!(check(r##"{"$ref": "#/nope"}"##), ErrorKind::Schema);
        assert_eq!(check(r#"{"$ref": "http://example.com/s.json"}"#), ErrorKind::Schema);
        assert_eq!(check(r#"{"items": [{}]}"#), ErrorKind::Schema);
        assert_eq!(check(r#"{"type": "float"}"#), ErrorKind::Schema);
    }

    #[test]
    fn cyclic_ref_is_an_error_not_a_crash() {
        let s = parse_document(r##"{"$ref": "#"}"##).unwrap();
        assert_eq!(validate(&Value::Null, &s).unwrap_err().kind, ErrorKind::Schema);
    }

    #[test]
    fn format_is_stable() {
        let e = vec![ValidationError { path: String::new(), keyword: "type", message: "x".into() }];
        assert_eq!(format_errors(&e), "1 schema violation:\n  - (root): x");
    }
}
