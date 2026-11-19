# beacon-ffi

A stable **C ABI** over [`beacon-core`](../beacon-core) — the foundation for
native bindings (Go via cgo, JVM via JNI/Panama, or any language with a C FFI).
Output is **byte-identical** to the Python and WebAssembly bindings; the
cross-language conformance corpus asserts it.

Deterministic: no clock, RNG, locale, environment, network or model.

## Contract

- Inputs are UTF-8, NUL-terminated C strings. A JSON *value* input (schema, hash
  value, tool-call arguments, template variables, citation kinds) is passed as
  JSON text and parsed by beacon's own strict parser.
- Each function returns a freshly allocated UTF-8 C string — free it with
  `beacon_string_free` — or `NULL` on error.
- On `NULL`, `beacon_last_error_code()` and `beacon_last_error_message()` return
  the stable beacon error code (e.g. `json.not_found`) and message for the
  **current thread**, valid until that thread's next beacon call. The error
  state is thread-local; the library is otherwise stateless.
- Structured results are beacon's **canonical JSON text**.
- Panics are caught at the boundary and surface as a `ffi.panic` error (the core
  is panic-free; this is defence in depth).

The full surface is in [`include/beacon.h`](include/beacon.h).

## Build

```sh
cargo build -p beacon-ffi --release
```

produces, in `target/release/`:

- `beacon_ffi.dll` / `libbeacon_ffi.so` / `libbeacon_ffi.dylib` — the shared
  library (`cdylib`);
- `libbeacon_ffi.a` — a static library (`staticlib`);
- plus an import library on Windows.

Link against it and include `beacon.h`. The crate's own Rust tests
(`cargo test -p beacon-ffi`) exercise the ABI — marshalling, error codes,
NUL-safety and `free` — without a C toolchain.

## Example

```c
#include "beacon.h"
#include <stdio.h>

int main(void) {
    char *out = beacon_redact("Email alice@example.com", "default", "[REDACTED:{label}]");
    if (out == NULL) {
        fprintf(stderr, "beacon: %s (%s)\n", beacon_last_error_message(), beacon_last_error_code());
        return 1;
    }
    printf("%s\n", out);      /* Email [REDACTED:email] */
    beacon_string_free(out);
    return 0;
}
```

## Status

The C ABI compiles and is Rust-tested here. Language bindings on top of it
(Go, JVM) and a C conformance runner that feeds this library the shared golden
corpus are the next step — each new binding is validated the moment it exists by
reusing `tests/conformance/corpus.json`.
