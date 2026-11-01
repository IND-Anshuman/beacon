//! Deterministic prompt templates.
//!
//! Syntax (a strict subset of `str.format`):
//!
//! * `{name}` — substitute variable `name` (`[A-Za-z_][A-Za-z0-9_]*`), escaped
//!   according to the escape mode.
//! * `{name!raw}` — substitute without escaping.
//! * `{{` and `}}` — literal braces.
//!
//! Anything else inside braces (format specs, attribute access, positional
//! fields, whitespace) is a `TemplateSyntaxError`. Substitution is a single
//! left-to-right pass: a value containing `{other}` is inserted literally and
//! never expanded again.

use crate::error::{BlockError, ErrorKind};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Escape {
    /// Insert values unchanged.
    None,
    /// Escape `&`, `<` and `>` so a value cannot open or close XML-style
    /// prompt sections such as `<user_input>...</user_input>`.
    Xml,
    /// Escape as the inside of a JSON string literal (no surrounding quotes).
    Json,
}

impl Escape {
    pub fn parse(s: &str) -> Result<Escape, BlockError> {
        match s {
            "none" => Ok(Escape::None),
            "xml" => Ok(Escape::Xml),
            "json" => Ok(Escape::Json),
            _ => Err(BlockError::invalid_argument(
                "template.invalid_escape",
                format!("escape must be 'xml', 'json' or 'none', got '{s}'"),
            )),
        }
    }

    fn apply(self, value: &str, out: &mut String) {
        match self {
            Escape::None => out.push_str(value),
            Escape::Xml => {
                for c in value.chars() {
                    match c {
                        '&' => out.push_str("&amp;"),
                        '<' => out.push_str("&lt;"),
                        '>' => out.push_str("&gt;"),
                        c => out.push(c),
                    }
                }
            }
            Escape::Json => {
                let mut quoted = String::with_capacity(value.len() + 2);
                crate::value::write_json_string(value, &mut quoted);
                out.push_str(&quoted[1..quoted.len() - 1]);
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Segment {
    Literal(String),
    Var {
        name: String,
        raw: bool,
        /// The placeholder as written, e.g. `{name!raw}`.
        source: String,
    },
}

fn syntax_error(code: &'static str, message: String, text: &str, byte: usize) -> BlockError {
    BlockError::at(ErrorKind::TemplateSyntax, code, message, text, byte)
}

fn valid_name(name: &str) -> bool {
    let mut chars = name.chars();
    matches!(chars.next(), Some(c) if c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// Parses a template into literal and variable segments.
pub fn parse(source: &str) -> Result<Vec<Segment>, BlockError> {
    let mut segments = Vec::new();
    let mut literal = String::new();
    let bytes = source.as_bytes();
    let mut i = 0;
    let mut lit_start = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'{' if bytes.get(i + 1) == Some(&b'{') => {
                literal.push_str(&source[lit_start..i]);
                literal.push('{');
                i += 2;
                lit_start = i;
            }
            b'}' if bytes.get(i + 1) == Some(&b'}') => {
                literal.push_str(&source[lit_start..i]);
                literal.push('}');
                i += 2;
                lit_start = i;
            }
            b'}' => {
                return Err(syntax_error(
                    "template.unmatched_close",
                    "single '}' is not allowed; write '}}' for a literal brace".to_string(),
                    source,
                    i,
                ));
            }
            b'{' => {
                literal.push_str(&source[lit_start..i]);
                let open = i;
                let Some(rel) = source[open + 1..].find(['}', '{']) else {
                    return Err(syntax_error(
                        "template.unterminated",
                        "unterminated '{'; write '{{' for a literal brace".to_string(),
                        source,
                        open,
                    ));
                };
                let close = open + 1 + rel;
                if bytes[close] == b'{' {
                    return Err(syntax_error(
                        "template.nested_brace",
                        "'{' inside a placeholder; write '{{' for a literal brace".to_string(),
                        source,
                        close,
                    ));
                }
                let inner = &source[open + 1..close];
                let (name, conversion) = match inner.split_once('!') {
                    Some((n, c)) => (n, Some(c)),
                    None => (inner, None),
                };
                if name.is_empty() {
                    return Err(syntax_error(
                        "template.empty_name",
                        "empty placeholder '{}'; positional fields are not supported".to_string(),
                        source,
                        open,
                    ));
                }
                if let Some(colon) = name.find(':') {
                    return Err(syntax_error(
                        "template.format_spec",
                        "format specs ('{name:...}') are not supported; format the value before passing it".to_string(),
                        source,
                        open + 1 + colon,
                    ));
                }
                if !valid_name(name) {
                    return Err(syntax_error(
                        "template.invalid_name",
                        format!("invalid variable name {:?}; names must match [A-Za-z_][A-Za-z0-9_]*", name),
                        source,
                        open + 1,
                    ));
                }
                let raw = match conversion {
                    None => false,
                    Some("raw") => true,
                    Some(other) => {
                        return Err(syntax_error(
                            "template.unknown_conversion",
                            format!("unknown conversion '!{other}'; only '!raw' is supported"),
                            source,
                            open + 1 + name.len(),
                        ));
                    }
                };
                if !literal.is_empty() {
                    segments.push(Segment::Literal(std::mem::take(&mut literal)));
                }
                segments.push(Segment::Var { name: name.to_string(), raw, source: source[open..=close].to_string() });
                i = close + 1;
                lit_start = i;
            }
            _ => i += 1,
        }
    }
    literal.push_str(&source[lit_start..]);
    if !literal.is_empty() {
        segments.push(Segment::Literal(literal));
    }
    Ok(segments)
}

/// Variable names in order of first appearance.
pub fn variables(source: &str) -> Result<Vec<String>, BlockError> {
    let mut names: Vec<String> = Vec::new();
    for seg in parse(source)? {
        if let Segment::Var { name, .. } = seg {
            if !names.contains(&name) {
                names.push(name);
            }
        }
    }
    Ok(names)
}

fn names_message(prefix: &str, names: &[String]) -> String {
    let quoted: Vec<String> = names.iter().map(|n| format!("'{n}'")).collect();
    let plural = if names.len() == 1 { "" } else { "s" };
    format!("{prefix}{plural}: {}", quoted.join(", "))
}

/// Renders a template. `vars` holds already-stringified values.
///
/// * Missing variables: error in strict mode, placeholder kept verbatim
///   otherwise.
/// * Unused variables: error in strict mode, ignored otherwise.
///
/// Missing variables are reported before unused ones; names are sorted.
pub fn render(source: &str, vars: &[(String, String)], escape: Escape, strict: bool) -> Result<String, BlockError> {
    let segments = parse(source)?;
    let lookup = |name: &str| vars.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str());

    let mut missing: Vec<String> = Vec::new();
    for seg in &segments {
        if let Segment::Var { name, .. } = seg {
            if lookup(name).is_none() && !missing.contains(name) {
                missing.push(name.clone());
            }
        }
    }
    if strict && !missing.is_empty() {
        missing.sort();
        let mut err = BlockError::new(
            ErrorKind::MissingVariable,
            "template.missing_variable",
            names_message("missing template variable", &missing),
        );
        err.names = missing;
        return Err(err);
    }
    if strict {
        let mut unused: Vec<String> = vars
            .iter()
            .map(|(k, _)| k)
            .filter(|k| !segments.iter().any(|s| matches!(s, Segment::Var { name, .. } if name == *k)))
            .cloned()
            .collect();
        if !unused.is_empty() {
            unused.sort();
            unused.dedup();
            let mut err = BlockError::new(
                ErrorKind::ExtraVariable,
                "template.extra_variable",
                names_message("unused template variable", &unused),
            );
            err.names = unused;
            return Err(err);
        }
    }

    let mut out = String::with_capacity(source.len());
    for seg in &segments {
        match seg {
            Segment::Literal(text) => out.push_str(text),
            Segment::Var { name, raw, source } => match lookup(name) {
                Some(value) if *raw => out.push_str(value),
                Some(value) => escape.apply(value, &mut out),
                None => out.push_str(source),
            },
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vars(pairs: &[(&str, &str)]) -> Vec<(String, String)> {
        pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
    }

    #[test]
    fn basic_render() {
        let out = render(
            "Hello {name}, your order #{order_id} is ready.",
            &vars(&[("name", "Alice"), ("order_id", "12345")]),
            Escape::Xml,
            true,
        )
        .unwrap();
        assert_eq!(out, "Hello Alice, your order #12345 is ready.");
    }

    #[test]
    fn no_recursive_expansion() {
        let out = render("{a} {b}", &vars(&[("a", "{b}"), ("b", "x")]), Escape::None, true).unwrap();
        assert_eq!(out, "{b} x");
    }

    #[test]
    fn escaping_modes() {
        let v = vars(&[("u", "</input> & \"x\"\n")]);
        assert_eq!(render("{u}", &v, Escape::Xml, true).unwrap(), "&lt;/input&gt; &amp; \"x\"\n");
        assert_eq!(render("{u!raw}", &v, Escape::Xml, true).unwrap(), "</input> & \"x\"\n");
        assert_eq!(render("{u}", &v, Escape::Json, true).unwrap(), "</input> & \\\"x\\\"\\n");
    }

    #[test]
    fn missing_and_extra() {
        let err = render("{b} {a} {b}", &[], Escape::None, true).unwrap_err();
        assert_eq!(err.kind, ErrorKind::MissingVariable);
        assert_eq!(err.names, vec!["a", "b"]);
        assert_eq!(err.message, "missing template variables: 'a', 'b'");
        let err = render("{a}", &vars(&[("a", "1"), ("z", "2")]), Escape::None, true).unwrap_err();
        assert_eq!(err.kind, ErrorKind::ExtraVariable);
        let out = render("{a} {b!raw}", &vars(&[("a", "1"), ("z", "2")]), Escape::None, false).unwrap();
        assert_eq!(out, "1 {b!raw}");
    }

    #[test]
    fn syntax_errors() {
        let code = |s: &str| parse(s).unwrap_err().code;
        assert_eq!(code("a } b"), "template.unmatched_close");
        assert_eq!(code("a { b"), "template.unterminated");
        assert_eq!(code("{}"), "template.empty_name");
        assert_eq!(code("{x:>10}"), "template.format_spec");
        assert_eq!(code("{ x }"), "template.invalid_name");
        assert_eq!(code("{x.y}"), "template.invalid_name");
        assert_eq!(code("{x!r}"), "template.unknown_conversion");
        assert_eq!(code("{a{b}"), "template.nested_brace");
    }

    #[test]
    fn literal_braces_and_unicode() {
        let out = render("{{\"k\": \"{v}\"}} — ✓", &vars(&[("v", "é")]), Escape::Json, true).unwrap();
        assert_eq!(out, "{\"k\": \"é\"} — ✓");
        assert_eq!(variables("{b}{a}{b}").unwrap(), vec!["b", "a"]);
    }
}
