# Adoption & Launch phase — what changed

Everything below is **uncommitted on `main`** for you to review and commit.
Nothing was committed, branched, PR'd, or published. No existing block output,
error code or message changed; the three gates (deterministic, provider-agnostic,
non-model) hold.

## A. Python framework adapters (8, thin & duck-typed)

New modules under `python/beacon/integrations/`, each with a fakes-based test,
an optional extra, and an index line — matching the `openai_sdk` convention
(duck-typed, normalize to `{"name","arguments"}`, provider-prefixed
`*.unknown_tool` codes, `.raw` on violations):

| Module | Test |
| --- | --- |
| `openai_agents.py` | `tests/test_integration_openai_agents.py` |
| `smolagents.py` | `tests/test_integration_smolagents.py` |
| `haystack.py` | `tests/test_integration_haystack.py` |
| `strands.py` | `tests/test_integration_strands.py` |
| `autogen.py` | `tests/test_integration_autogen.py` |
| `crewai.py` | `tests/test_integration_crewai.py` |
| `agno.py` | `tests/test_integration_agno.py` |
| `semantic_kernel.py` | `tests/test_integration_semantic_kernel.py` |

Also: one shared helper `validate_value()` added to `integrations/_common.py`
(for the "already-structured" path); 8 new extras in `pyproject.toml`; 8 index
lines in `integrations/__init__.py`.

The Haystack component needs Haystack installed (its test `importorskip`s, so it
skips here); its core `validate_replies()` is duck-typed and tested. Every other
adapter is fully exercised with `SimpleNamespace`/dict fakes — no framework
installs required.

## B. Vercel AI SDK adapter (TypeScript, on beacon-js)

- `crates/beacon-js/pkg/vercel.mjs` + `vercel.d.ts` — `validatedToolCalls`,
  `parseOutput`, `toolSchemas`; duck-typed, same behavior/codes as the Python
  adapters (`vercel.unknown_tool`, `vercel.invalid_arguments`, `.raw`).
- `package.json`: new `./vercel` subpath export + files entries.
- `crates/beacon-js/test/vercel.test.mjs` (Node, fakes). README section added.

## C. Recipes docs (symptom-organized)

`website/src/content/docs/recipes/` — an overview + **15 symptom pages**, each
ending in "What it does not do". Registered in the sidebar (`astro.config.mjs`).

## D. Benchmark page

`website/src/content/docs/guarantees/overhead.mdx` — the **real** measured
per-call overhead (1–10 µs/block), from `benches/determinism_overhead.py` on a
release build (beacon 1.0.0, CPython 3.14.7, Intel Core Ultra 5 225H). Numbers
are measured, not invented; the command to reproduce is on the page.

## E. Outreach drafts

`docs/outreach/{langchain,llamaindex,pydantic-ai,dspy}.md` + `README.md` —
"How to use beacon with X" pages in each project's voice, with runnable examples
against the shipped adapters. **Drafts only — you submit the PRs.**

## F. Launch checklist

`docs/outreach/launch-checklist.md`.

## G. Developer-experience pass (new)

Make a beacon error easy to act on, and the package easy to diagnose — all pure
Python, additive, with **no change to any existing output, error `code` or
message** (so no rebuild and no snapshot churn).

- **`BeaconError.explain()`** — deterministic long-form text: `[code] message`,
  then a `Cause:` / `Fix:` drawn from a per-code guidance registry, then any
  position / field context (offset+line+column, the schema violations, the
  template variable names, the snapshot path). No clock, colour or environment.
- **`BeaconError.details()`** — the same error as a JSON-friendly dict
  (`code`, `message`, and the non-`None` structured fields; tuples → lists), for
  logging or returning the error as data.
- **`beacon.explain_code(code)`** (also exported top-level) — guidance for a bare
  code with no instance in hand; matches the exact code, then a `*.suffix` family
  (`crewai.unknown_tool`), then a `prefix.*` family (`json.unexpected_end`).
- **CLI**: `beacon doctor` (versions + pinned data versions, for bug reports),
  `beacon explain <code>`, and a global `beacon --explain <cmd> …` that prints the
  long form when a command fails. Guidance text is ASCII-only so redirected
  output never raises on a Windows cp1252 pipe.
- **No ambient logging** — confirmed: blocks write to neither stdout nor the root
  logger. All of the above is opt-in, alongside the existing structured
  diagnostics (the repair log, `Pipeline` hash traces).
- **Docs**: a new recipe `recipes/error-i-dont-understand.mdx` (every code →
  cause + fix), an Exceptions-section note in `reference/api.mdx`, and an overview
  row.

Files: `python/beacon/errors.py`, `python/beacon/cli.py`,
`python/beacon/__init__.py`; tests `tests/test_errors_explain.py` (+ CLI tests in
`tests/test_cli.py`, `tests/test_async.py` surface-set exclusion);
`website/.../recipes/error-i-dont-understand.mdx`, `recipes/overview.mdx`,
`reference/api.mdx`, `astro.config.mjs`.

## Verified green (re-run any of these)

- `pytest --beacon-snapshot check` → **836 passed, 3 skipped** (incl. the 28-case
  cross-language parity corpus; +16 for the DX pass).
- `ruff check python tests examples benches` → clean.
- `cargo clippy --all-targets` (default and `--no-default-features`) → clean.
  (No Rust changed this phase.)
- `npm run build` in `website/` → 50 pages, no broken links.
- `node crates/beacon-js/test/vercel.test.mjs` and `.../smoke.mjs` → pass.

## What you need to do

1. **Pick the version.** `llm-beacon` on npm is already live at **1.0.0** without
   these features. These are backward-compatible additions → a **minor** bump
   (suggested **1.1.0**) in `Cargo.toml`, `pyproject.toml`,
   `crates/beacon-js/pkg/package.json`; `cargo check --workspace` to refresh both
   lockfiles; add a `1.1.0` CHANGELOG + website-changelog section.
2. **Commit** everything on `main`.
3. **Publish** (your accounts): PyPI via GitHub Release, `cargo publish -p
   beacon-core`, `npm publish` from `crates/beacon-js/pkg` (now ships
   `./vercel`). See `docs/releasing.md`.
4. **Submit** the four outreach drafts to each framework's docs, per their
   contribution guides.
5. Optionally wire `tests/test_integration_*.py` for the new frameworks into CI,
   and `node crates/beacon-js/test/vercel.test.mjs` alongside the existing smoke
   test in the `js` CI job.

Full detail: `docs/outreach/launch-checklist.md`.
