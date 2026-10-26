//! Deterministic content hashing.
//!
//! Values are fed to BLAKE3 as a type-tagged canonical encoding, documented in
//! `docs/determinism_guarantees.md`. Changing the encoding is a major-version
//! change, so it is spelled out byte by byte here.

use crate::error::BlockError;
use crate::value::Value;

/// Streams the canonical encoding of a value into BLAKE3.
///
/// Callers feed containers as a header (`begin_list` / `begin_map`) followed
/// by their items; map entries must be fed sorted by the key's UTF-8 bytes.
pub struct CanonicalHasher {
    hasher: blake3::Hasher,
}

impl Default for CanonicalHasher {
    fn default() -> Self {
        Self::new()
    }
}

impl CanonicalHasher {
    pub fn new() -> Self {
        CanonicalHasher { hasher: blake3::Hasher::new() }
    }

    fn len_prefix(&mut self, tag: u8, len: usize) {
        self.hasher.update(&[tag]);
        self.hasher.update(&(len as u64).to_be_bytes());
    }

    pub fn null(&mut self) {
        self.hasher.update(b"n");
    }

    pub fn boolean(&mut self, b: bool) {
        self.hasher.update(if b { b"t" } else { b"f" });
    }

    /// An integer given as canonical decimal text (optional `-`, no leading
    /// zeros, `0` for zero).
    pub fn int_decimal(&mut self, digits: &str) {
        self.hasher.update(b"i");
        self.hasher.update(digits.as_bytes());
        self.hasher.update(b";");
    }

    pub fn int(&mut self, i: i64) {
        self.int_decimal(&i.to_string());
    }

    pub fn float(&mut self, f: f64) {
        let bits = if f.is_nan() { 0x7ff8_0000_0000_0000u64 } else { f.to_bits() };
        self.hasher.update(b"d");
        self.hasher.update(&bits.to_be_bytes());
    }

    pub fn string(&mut self, s: &str) {
        self.len_prefix(b's', s.len());
        self.hasher.update(s.as_bytes());
    }

    pub fn bytes(&mut self, b: &[u8]) {
        self.len_prefix(b'b', b.len());
        self.hasher.update(b);
    }

    pub fn begin_list(&mut self, len: usize) {
        self.len_prefix(b'l', len);
    }

    pub fn begin_map(&mut self, len: usize) {
        self.len_prefix(b'm', len);
    }

    /// Hex digest truncated to `length` characters (1–64).
    pub fn finish(&self, length: usize) -> String {
        let hex = self.hasher.finalize().to_hex();
        hex.as_str()[..length.min(64)].to_string()
    }

    /// Feeds a [`Value`]. Object keys are sorted by UTF-8 bytes.
    pub fn value(&mut self, v: &Value) {
        match v {
            Value::Null => self.null(),
            Value::Bool(b) => self.boolean(*b),
            Value::Int(i) => self.int(*i),
            Value::BigInt(s) => self.int_decimal(s),
            Value::Float(f) => self.float(*f),
            Value::Str(s) => self.string(s),
            Value::Array(items) => {
                self.begin_list(items.len());
                for item in items {
                    self.value(item);
                }
            }
            Value::Object(entries) => {
                let mut sorted: Vec<&(String, Value)> = entries.iter().collect();
                sorted.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
                self.begin_map(sorted.len());
                for (k, v) in sorted {
                    self.string(k);
                    self.value(v);
                }
            }
        }
    }
}

pub fn check_length(length: usize) -> Result<usize, BlockError> {
    if (1..=64).contains(&length) {
        Ok(length)
    } else {
        Err(BlockError::invalid_argument(
            "hash.invalid_length",
            format!("length must be between 1 and 64, got {length}"),
        ))
    }
}

/// Hashes a [`Value`].
pub fn hash_value(v: &Value, length: usize) -> Result<String, BlockError> {
    let length = check_length(length)?;
    let mut h = CanonicalHasher::new();
    h.value(v);
    Ok(h.finish(length))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn obj(pairs: Vec<(&str, Value)>) -> Value {
        Value::Object(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
    }

    #[test]
    fn key_order_does_not_matter() {
        let a = obj(vec![("a", Value::Int(1)), ("b", Value::Int(2))]);
        let b = obj(vec![("b", Value::Int(2)), ("a", Value::Int(1))]);
        assert_eq!(hash_value(&a, 16).unwrap(), hash_value(&b, 16).unwrap());
    }

    #[test]
    fn types_are_distinguished() {
        let values = [
            Value::Int(1),
            Value::Float(1.0),
            Value::Bool(true),
            Value::Str("1".into()),
            Value::Array(vec![Value::Int(1)]),
            obj(vec![("0", Value::Int(1))]),
            Value::Null,
            Value::Float(-0.0),
            Value::Float(0.0),
        ];
        let hashes: Vec<String> = values.iter().map(|v| hash_value(v, 64).unwrap()).collect();
        for i in 0..hashes.len() {
            for j in i + 1..hashes.len() {
                assert_ne!(hashes[i], hashes[j], "{:?} vs {:?}", values[i], values[j]);
            }
        }
    }

    #[test]
    fn list_order_matters() {
        let a = Value::Array(vec![Value::Int(1), Value::Int(2)]);
        let b = Value::Array(vec![Value::Int(2), Value::Int(1)]);
        assert_ne!(hash_value(&a, 16).unwrap(), hash_value(&b, 16).unwrap());
    }

    #[test]
    fn nan_is_canonical() {
        let a = Value::Float(f64::NAN);
        let b = Value::Float(-f64::NAN);
        assert_eq!(hash_value(&a, 16).unwrap(), hash_value(&b, 16).unwrap());
    }

    #[test]
    fn known_vector_is_stable() {
        // Pinned output: if this changes, the canonical encoding changed and
        // every user's snapshot ids change with it. That is a major version.
        let v = obj(vec![("intent", Value::Str("cancel".into())), ("confidence", Value::Float(0.9))]);
        // Same digest as `beacon.hash_content({"intent": "cancel", "confidence": 0.9})`
        // (snapshots/hash/pinned_digests.yaml), so the Value and Python paths agree.
        assert_eq!(hash_value(&v, 16).unwrap(), "f41e0685bbe3fb6d");
        assert_eq!(hash_value(&Value::Null, 16).unwrap(), "a74e0b1433b54b7a");
        let mut h = CanonicalHasher::new();
        h.string("");
        assert_eq!(h.finish(16), blake3::hash(&[b's', 0, 0, 0, 0, 0, 0, 0, 0]).to_hex()[..16].to_string());
    }

    #[test]
    fn length_bounds() {
        assert!(hash_value(&Value::Null, 0).is_err());
        assert!(hash_value(&Value::Null, 65).is_err());
        assert_eq!(hash_value(&Value::Null, 1).unwrap().len(), 1);
    }
}
