//! Canonical text normalization.
//!
//! The steps always run in this fixed order (each one only if enabled):
//!
//! 1. Unicode normalization (`form`, default NFKC)
//! 2. accent stripping (decompose, drop combining marks, re-apply `form`)
//! 3. lowercasing (full Unicode case mapping, locale-independent)
//! 4. removal of control characters (category Cc, except whitespace)
//! 5. removal of zero-width characters (U+200B, U+2060, U+FEFF)
//! 6. whitespace collapsing (runs of Unicode whitespace → one space, or one
//!    newline when `preserve_newlines` is set and the run contains a line break)
//! 7. stripping leading/trailing whitespace

use unicode_normalization::UnicodeNormalization;
use unicode_normalization::char::is_combining_mark;

use crate::error::BlockError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Form {
    Nfc,
    Nfd,
    Nfkc,
    Nfkd,
}

impl Form {
    /// Parses a form name, case-insensitively.
    pub fn parse(name: &str) -> Result<Form, BlockError> {
        match name.to_ascii_uppercase().as_str() {
            "NFC" => Ok(Form::Nfc),
            "NFD" => Ok(Form::Nfd),
            "NFKC" => Ok(Form::Nfkc),
            "NFKD" => Ok(Form::Nfkd),
            _ => Err(BlockError::invalid_argument(
                "normalize.invalid_form",
                format!("form must be one of 'NFC', 'NFD', 'NFKC', 'NFKD' or None, got '{name}'"),
            )),
        }
    }

    fn apply(self, s: &str) -> String {
        match self {
            Form::Nfc => s.nfc().collect(),
            Form::Nfd => s.nfd().collect(),
            Form::Nfkc => s.nfkc().collect(),
            Form::Nfkd => s.nfkd().collect(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Options {
    pub form: Option<Form>,
    pub strip_accents: bool,
    pub lowercase: bool,
    pub remove_control: bool,
    pub remove_zero_width: bool,
    pub collapse_whitespace: bool,
    pub preserve_newlines: bool,
    pub strip: bool,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            form: Some(Form::Nfkc),
            strip_accents: false,
            lowercase: false,
            remove_control: true,
            remove_zero_width: true,
            collapse_whitespace: true,
            preserve_newlines: false,
            strip: true,
        }
    }
}

fn is_zero_width(c: char) -> bool {
    matches!(c, '\u{200B}' | '\u{2060}' | '\u{FEFF}')
}

fn is_line_break(c: char) -> bool {
    matches!(c, '\n' | '\r' | '\u{0B}' | '\u{0C}' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

pub fn normalize(text: &str, opts: &Options) -> String {
    let mut s = match opts.form {
        Some(form) => form.apply(text),
        None => text.to_string(),
    };

    if opts.strip_accents {
        let stripped: String = s.nfd().filter(|c| !is_combining_mark(*c)).collect();
        s = match opts.form {
            Some(form) => form.apply(&stripped),
            None => stripped.nfc().collect(),
        };
    }

    if opts.lowercase {
        s = s.to_lowercase();
    }

    if opts.remove_control || opts.remove_zero_width {
        s.retain(|c| {
            !((opts.remove_control && c.is_control() && !c.is_whitespace())
                || (opts.remove_zero_width && is_zero_width(c)))
        });
    }

    if opts.collapse_whitespace {
        s = collapse(&s, opts.preserve_newlines);
    }

    if opts.strip {
        let trimmed = s.trim();
        if trimmed.len() != s.len() {
            s = trimmed.to_string();
        }
    }
    s
}

fn collapse(s: &str, preserve_newlines: bool) -> String {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if !c.is_whitespace() {
            out.push(c);
            continue;
        }
        let mut has_break = is_line_break(c);
        while let Some(&next) = chars.peek() {
            if !next.is_whitespace() {
                break;
            }
            has_break |= is_line_break(next);
            chars.next();
        }
        out.push(if preserve_newlines && has_break { '\n' } else { ' ' });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn n(s: &str) -> String {
        normalize(s, &Options::default())
    }

    #[test]
    fn defaults() {
        assert_eq!(n("Hello   World\n\n"), "Hello World");
        assert_eq!(n("Hello\tWorld"), "Hello World");
        assert_eq!(n("ﬁle"), "file"); // NFKC ligature
        assert_eq!(n("a\u{200B}b\u{0007}c"), "abc");
        assert_eq!(n("  \u{00A0}x\u{3000}y "), "x y");
        assert_eq!(n(""), "");
    }

    #[test]
    fn accents_and_case() {
        let opts = Options { strip_accents: true, lowercase: true, ..Options::default() };
        assert_eq!(normalize("Café CRÈME", &opts), "cafe creme");
    }

    #[test]
    fn preserve_newlines() {
        let opts = Options { preserve_newlines: true, ..Options::default() };
        assert_eq!(normalize("a  b \r\n\r\n  c", &opts), "a b\nc");
    }

    #[test]
    fn no_form_keeps_compatibility_chars() {
        let opts = Options { form: None, ..Options::default() };
        assert_eq!(normalize("ﬁle", &opts), "ﬁle");
    }

    #[test]
    fn invalid_form() {
        assert!(Form::parse("nfkc").is_ok());
        assert_eq!(Form::parse("NFX").unwrap_err().code, "normalize.invalid_form");
    }
}
