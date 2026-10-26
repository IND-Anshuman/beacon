//! The error type shared by every block.
//!
//! Errors are data: a kind (which Python exception class to raise), a stable
//! machine-readable `code`, a stable human-readable `message`, and, for errors
//! about a piece of text, the position of the problem. Messages never contain
//! timestamps, addresses or anything else that varies between runs.

use std::fmt;

/// Which Python exception class an error maps to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorKind {
    /// `beacon.MalformedOutputError`
    Malformed,
    /// `beacon.NoJSONFoundError`
    NoJsonFound,
    /// `beacon.NoToolCallFoundError`
    NoToolCallFound,
    /// `beacon.TemplateSyntaxError`
    TemplateSyntax,
    /// `beacon.MissingVariableError`
    MissingVariable,
    /// `beacon.ExtraVariableError`
    ExtraVariable,
    /// `beacon.SchemaError` (the schema itself is invalid or unsupported)
    Schema,
    /// `ValueError` (an argument is out of range or malformed)
    InvalidArgument,
    /// `TypeError` (an argument has an unsupported type)
    InvalidType,
}

/// A position in a piece of text, counted the way Python counts: `offset` is a
/// code-point index into the `str`, `line` and `column` are 1-based.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TextPos {
    pub offset: usize,
    pub line: usize,
    pub column: usize,
}

impl TextPos {
    /// Computes the position of byte offset `byte` in `text`.
    ///
    /// `byte` is clamped to the text length and moved back to a char boundary,
    /// so this never panics.
    pub fn from_byte(text: &str, byte: usize) -> TextPos {
        let mut b = byte.min(text.len());
        while b > 0 && !text.is_char_boundary(b) {
            b -= 1;
        }
        let prefix = &text[..b];
        let offset = prefix.chars().count();
        let line = prefix.matches('\n').count() + 1;
        let line_start = prefix.rfind('\n').map_or(0, |i| i + 1);
        let column = prefix[line_start..].chars().count() + 1;
        TextPos { offset, line, column }
    }
}

/// An error produced by a block.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BlockError {
    pub kind: ErrorKind,
    pub code: &'static str,
    pub message: String,
    pub position: Option<TextPos>,
    /// Variable names for template errors (sorted, unique).
    pub names: Vec<String>,
}

impl BlockError {
    pub fn new(kind: ErrorKind, code: &'static str, message: impl Into<String>) -> Self {
        BlockError { kind, code, message: message.into(), position: None, names: Vec::new() }
    }

    /// An error about `text` at byte offset `byte`. The position is appended to
    /// the message as `(line L, column C)`.
    pub fn at(kind: ErrorKind, code: &'static str, message: impl Into<String>, text: &str, byte: usize) -> Self {
        let pos = TextPos::from_byte(text, byte);
        let mut message = message.into();
        message.push_str(&format!(" (line {}, column {})", pos.line, pos.column));
        BlockError { kind, code, message, position: Some(pos), names: Vec::new() }
    }

    pub fn invalid_argument(code: &'static str, message: impl Into<String>) -> Self {
        BlockError::new(ErrorKind::InvalidArgument, code, message)
    }
}

impl fmt::Display for BlockError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BlockError {}

/// Describes a character for an error message: `'x'` for printable
/// characters (`"'"` for a single quote), `U+000A` for everything else.
pub fn describe_char(c: char) -> String {
    if c.is_control() || c.is_whitespace() || is_invisible(c) {
        format!("U+{:04X}", c as u32)
    } else if c == '\'' {
        "\"'\"".to_string()
    } else {
        format!("'{c}'")
    }
}

fn is_invisible(c: char) -> bool {
    matches!(c, '\u{200B}'..='\u{200F}' | '\u{2028}'..='\u{202E}' | '\u{2060}'..='\u{2064}' | '\u{FEFF}')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn text_pos_counts_code_points() {
        let text = "héllo\nwörld";
        let byte = text.find('r').unwrap_or(0);
        let pos = TextPos::from_byte(text, byte);
        assert_eq!(pos.offset, 8);
        assert_eq!(pos.line, 2);
        assert_eq!(pos.column, 3);
    }

    #[test]
    fn text_pos_clamps_and_snaps_to_boundary() {
        let text = "é";
        assert_eq!(TextPos::from_byte(text, 1).offset, 0);
        assert_eq!(TextPos::from_byte(text, 99).offset, 1);
    }

    #[test]
    fn describe_char_variants() {
        assert_eq!(describe_char('a'), "'a'");
        assert_eq!(describe_char('\''), "\"'\"");
        assert_eq!(describe_char('\n'), "U+000A");
        assert_eq!(describe_char('\u{200B}'), "U+200B");
    }
}
