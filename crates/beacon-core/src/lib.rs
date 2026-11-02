//! beacon-core: deterministic, tested building blocks for AI pipelines.
//!
//! Every block in this crate is pure: the same input produces byte-identical
//! output on every machine, forever. There is no clock, RNG, locale, env,
//! network, or model call anywhere in the core. Error `code`s and messages are
//! part of the public contract and are stable across releases.
//!
//! Language bindings (the PyO3 extension `beacon._beacon_native`, the wasm
//! playground bridge, and the npm package) are thin wrappers over these
//! modules and add no behaviour of their own.

/// The Unicode version of the bundled normalization tables, as
/// `(major, minor, patch)`. Exposed so bindings report the same version that
/// the `normalize` block's tables were built against.
pub fn unicode_version() -> (u8, u8, u8) {
    unicode_normalization::UNICODE_VERSION
}

pub mod error;
pub mod extract_json;
pub mod hash;
pub mod json;
pub mod normalize;
pub mod parse_tool_call;
pub mod partial;
pub mod redact;
pub mod repair;
pub mod retry;
pub mod template;
pub mod validate_schema;
pub mod value;
