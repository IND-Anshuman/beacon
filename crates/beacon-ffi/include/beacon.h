/* beacon — C ABI over the deterministic beacon-core Rust library.
 *
 * Every function takes UTF-8, NUL-terminated C strings and returns a freshly
 * allocated UTF-8 C string (free it with beacon_string_free), or NULL on error.
 * After a NULL return, beacon_last_error_code() / beacon_last_error_message()
 * give the stable beacon error code and message for the CURRENT THREAD, valid
 * until that thread's next beacon call.
 *
 * Structured results are beacon's canonical JSON text — byte-identical to the
 * Python and WebAssembly bindings (asserted by the cross-language conformance
 * corpus). JSON-value inputs (schemas, hash values, tool-call arguments,
 * template variables, citation kinds) are passed as JSON text.
 *
 * Deterministic: no clock, RNG, locale, environment, network or model.
 */
#ifndef BEACON_H
#define BEACON_H

#include <stddef.h> /* size_t */

#ifdef __cplusplus
extern "C" {
#endif

/* Free a string returned by any beacon_* function. NULL is a no-op. */
void beacon_string_free(char *s);

/* Last error on this thread (NULL if the last call succeeded). Borrowed; valid
 * until the next beacon call on this thread — copy if you need to keep it. */
const char *beacon_last_error_code(void);
const char *beacon_last_error_message(void);

/* text -> JSON value (canonical JSON text; "null" when required=0 and none). */
char *beacon_extract_json(const char *text, const char *select, const char *kind, int required);

/* text -> {value, repairs, incomplete}. */
char *beacon_repair_json(const char *text);

/* streaming prefix -> {value, complete, consumed}. */
char *beacon_parse_partial(const char *text);

/* text -> [ {name, arguments[, format]} ]. */
char *beacon_parse_tool_calls(const char *text, int include_format);

/* instance JSON, schema JSON -> [ {path, keyword, message} ] ([] if valid). */
char *beacon_schema_errors(const char *instance, const char *schema);

/* text -> normalized text. `form` may be NULL to skip Unicode normalization. */
char *beacon_normalize(const char *text, const char *form, int strip_accents, int lowercase,
                       int remove_control, int remove_zero_width, int collapse_whitespace,
                       int preserve_newlines, int strip);

/* JSON value text -> BLAKE3 hex digest of `length` bytes (1..=64). */
char *beacon_hash_content(const char *json_value, size_t length);

/* JSON array text (prompt parts) -> cache key (hex). */
char *beacon_cache_key(const char *parts_json, size_t length);

/* text -> redacted text. */
char *beacon_redact(const char *text, const char *policy, const char *replacement);

/* text -> [ {label, start, end, text} ]. */
char *beacon_detect_pii(const char *text, const char *policy);

/* source, variables JSON object text -> rendered text. */
char *beacon_template(const char *source, const char *variables_json, const char *escape, int strict);

/* template source -> [ names ]. */
char *beacon_template_variables(const char *source);

/* text, kinds JSON array text -> [ {kind, ref, start, end, text} ]. */
char *beacon_extract_citations(const char *text, const char *kinds_json);

/* text -> [ {label, severity, start, end, text, path} ]. */
char *beacon_detect_injection(const char *text, const char *policy);

/* arguments JSON text -> [ {label, severity, start, end, text, path} ]. */
char *beacon_scan_arguments(const char *arguments_json, const char *policy);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* BEACON_H */
