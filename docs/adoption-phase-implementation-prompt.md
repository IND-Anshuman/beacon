# beacon — Adoption & Launch phase (post-v1.0) · master implementation prompt

You are implementing the **Adoption & Launch** phase of **beacon**, a library of
deterministic, tested building blocks for AI pipelines. v0.1–v1.0 are done (the
core blocks, `repair_json`, async `beacon.aio`, the Cargo workspace with
`beacon-core` on crates.io, the `beacon-js` npm/WASM package, and the streaming
`parse_partial`, `extract_citations`, `detect_injection`/`scan_arguments`
blocks). This phase is about **reach**: the remaining framework adapters,
problem-shaped docs, a published benchmark, discovery via other projects' docs,
and launch readiness. Follow this brief exactly.

---

## 0. Mission & the three gates

beacon's value is a **determinism contract**: same input → byte-identical
output on every machine, forever, error messages included. Everything you add
must pass all three gates, or do not build it:

1. **Deterministic** — no clock, RNG, locale, env, network, or model call in any
   block.
2. **Provider-agnostic** — it sits at the boundary between model output and
   application code, never inside a provider SDK.
3. **Non-model** — never calls a model, scores a model, or stores vectors.

Adapters are thin boundary glue, **not** framework features. Keep each one small.

---

## 1. Hard constraints (non-negotiable)

- **Git is the maintainer's, always.** Do **not** commit, open PRs, create or
  switch branches, or publish anything. All work stays on `main` as uncommitted
  edits for the maintainer to review and commit. Every external submission —
  PRs into other projects' docs, `cargo publish`, `npm publish`, launch posts —
  is the maintainer's to make. You prepare; they ship. (See the `never-commit`
  memory.)
- **Three gates** (§0) for anything new. Re-read `docs/plan.md` and
  `docs/determinism_guarantees.md`; existing error `code`s and messages are
  stable — never change them.
- **"What NOT to build"** still holds: no chat client / model wrapper, no
  constrained decoding, no eval/scoring framework, no RAG/vector store, no agent
  framework, no silent JSON repair, no ML-based PII, no Pydantic or Tenacity
  reimplementation. Adapters must not reimplement any of a framework's own job.
- **Adapter convention** (match `integrations/openai_sdk.py`,
  `anthropic_sdk.py`, `litellm.py`, `mcp.py`): duck-typed, **no hard dependency**
  on the framework (import it lazily or not at all; accept dicts / `SimpleNamespace`
  / the real objects); normalize to beacon's existing shapes
  (`{"name", "arguments"}` for tool calls); validate with `validate_schema`;
  raise `MalformedOutputError` with a provider-prefixed code
  (`crewai.unknown_tool`, etc.) for unknown tools and attach `.raw` on schema
  violations. Reuse `_common.parse_structured` / `schema_for`.
- **Keep green**: full `pytest` (currently ~685 passing), `ruff check`, and
  `cargo clippy` stay clean; each new adapter ships with tests using fakes +
  `pytest.importorskip`, an optional extra in `pyproject.toml`, and an entry in
  `integrations/__init__.py`.
- **Build recipe (this machine, Windows GNU, no MSVC)** — only needed if you
  touch Rust (this phase is mostly Python/docs):
  `RUSTFLAGS="-L native=C:/Users/knigh/AppData/Local/Programs/Python/Python314/libs" PYO3_USE_RAW_DYLIB=0 .venv/Scripts/python.exe -m maturin develop`;
  pure core: `PYO3_USE_RAW_DYLIB=0 cargo test --no-default-features`. See the
  `windows-gnu-build` memory.

---

## 2. Current state (verified)

- Workspace: `crates/beacon-core` (pure, on crates.io), `crates/beacon-python`
  (PyO3 `_beacon_native`), `crates/beacon-wasm`, `crates/beacon-js` (npm package
  in `crates/beacon-js/pkg/`).
- Core blocks incl. v1.0: `parse_partial`, `extract_citations`,
  `detect_injection`, `scan_arguments` — all present and fuzz-tested.
- **Integrations present** (10): `openai_sdk`, `anthropic_sdk`, `gemini_sdk`,
  `litellm`, `mcp`, `otel`, `langchain`, `llamaindex`, `pydantic_ai`, `dspy`.
- Docs site content (`website/src/content/docs/`): `getting-started`, `blocks`,
  `integrations`, `guarantees`, `snapshots`, `reference`. **No `recipes/`
  section yet.** `benches/determinism_overhead.py` exists but its numbers are
  **not published**.

---

## 3. Work items

### A. Remaining Python framework adapters (thin, duck-typed)

Add one module per framework under `python/beacon/integrations/`, each ~30–60
lines, following the convention in §1. None is present yet:

| Module | Framework | Surface to cover |
|---|---|---|
| `openai_agents.py` | OpenAI Agents SDK | tool callbacks → validate args; final output → `parse_structured` |
| `smolagents.py` | smolagents | `Tool` objects → schemas; final-answer parsing |
| `haystack.py` | Haystack | an output-adapter component that extracts + validates |
| `strands.py` | Strands Agents (AWS) | tool specs → schemas; tool-use results |
| `autogen.py` | AutoGen | tool/function messages → `{"name","arguments"}` |
| `crewai.py` | CrewAI | task output parsing + validation |
| `agno.py` | Agno | tool results |
| `semantic_kernel.py` | Semantic Kernel | tool results / function-call args |

For each: a `validated_tool_call(...)` and/or output-parsing entry mirroring
`openai_sdk`; an async variant where the framework is async-first; an optional
extra in `pyproject.toml`; tests with `SimpleNamespace`/dict fakes +
`importorskip`; an `integrations/__init__.py` docstring line. If a framework
offers nothing beyond what an existing adapter covers, say so and skip it rather
than pad.

### B. Vercel AI SDK adapter (TypeScript, on `beacon-js`)

The one TS-side adapter: parse/validate Vercel AI SDK outputs and tool calls
using `beacon-js`. Keep it in the `beacon-js` package (or a documented
companion), with `.d.ts` types and parity with the Python adapters' behavior.

### C. Problem-shaped recipe docs (roadmap §4)

Add a `recipes/` section to `website/src/content/docs/` organized **by symptom,
not by API**. Each page: **Symptom** (the error the user actually sees) →
**Minimal fix** → **What it guarantees** → **What it does not do** (this last
section is what makes beacon credible). Cover at least: prose instead of JSON;
trailing comma; output cut off mid-object; tool args came back as a string;
model called a nonexistent tool; useless schema-validation error; PII in the
prompt; 429 retry storm; "output changed and I don't know why"; two providers,
different shapes; closed-set intents; prove no PII left; expensive prompt prefix;
SQL injection in a tool arg; replay last week's failures. Link each to the block
that solves it.

### D. Benchmark page (roadmap §5)

Run `benches/determinism_overhead.py`, and publish the numbers (Rust core vs a
pure-Python equivalent) as a docs-site page. Make it reproducible (document the
command and machine); present it as a measured fact, not a claim. Do not invent
numbers — run it and report what it prints.

### E. Framework-docs PR drafts (roadmap §3 — highest-leverage discovery)

Draft "How to use beacon with X" documentation pages for **LangChain,
LlamaIndex, Pydantic AI, and DSPy**, written for *their* docs in *their* style,
each with a runnable minimal example. **Leave them as draft files** in the repo
(e.g. `docs/outreach/`) for the maintainer to submit — you do not open the PRs.
These are the single highest-leverage adoption channel; make them genuinely good.

### F. Launch readiness checklist (roadmap §7)

A `docs/outreach/launch-checklist.md`: what must be true before launch (PyPI
`llm-beacon`, crates.io `beacon-core`, npm `beacon-js` published by the
maintainer; README/quickstart accurate; `llms.txt`, `og.png`, `robots.txt`
in place — they already exist in `website/public/`; docs site deployed). The
actual launch posts and publishes are the maintainer's; this is the checklist,
not the act.

### G. Developer-experience pass (make the package effortless to use)

Adoption dies on friction. Before launch, do a pass whose only goal is that a
developer who hits a problem gets unstuck fast — without breaking a gate.

- **Errors that teach.** Audit every `MalformedOutputError`, schema error and
  repair failure: each should say *what* failed, *where* in the input
  (path / offset), the offending fragment, and the fix. Add an `.explain()`
  long form where the short message must stay stable. Keep `code`s frozen; any
  reworded message is a versioned behaviour change with updated snapshots. (This
  dovetails with the "useless schema-validation error" recipe in C.)
- **No ambient side effects.** Confirm no block writes to stdout or the root
  logger on its own. A caller who wants to see what happened gets it from
  returned diagnostics (the repair log, `Pipeline` hash traces) or an optional
  callback — documented as "beacon never logs on its own."
- **Readable results & a troubleshooting recipe.** Good `__repr__` on result
  objects; a `recipes/` page "beacon raised an error I don't understand"
  mapping each `code` to cause + fix; a `beacon doctor` CLI that prints versions
  and the pinned data versions (Unicode, hash encoding, snapshot format).
- **Docs ergonomics.** Every public symbol: a docstring stating what it does,
  its guarantee, and what it does *not* do; a copy-paste quickstart that runs;
  complete type stubs.

This is the immediate, shippable slice of the larger DX direction proposed as
pillar E of the v2.0 prompt — keep it additive and gate-clean.

---

## 4. Sequencing

1. **A** — the Python adapters, one at a time, suite green after each. Highest
   code value, lowest risk.
2. **C** + **D** — recipe docs and the benchmark page (independent of A).
3. **B** — the Vercel AI SDK TS adapter (needs `beacon-js`).
4. **E** + **F** — outreach drafts and the launch checklist, last, once the
   surface they describe is final.
5. **G** — the DX pass, woven through A–D and finished before launch: errors and
   docstrings get polished as you touch each block; the troubleshooting recipe
   and `beacon doctor` land with the recipe section (C).

Do the four framework-docs PR drafts (E) in parallel with the rest if convenient
— they have the longest external lead time once the maintainer submits them.

---

## 5. Definition of done

- Each new adapter: thin, duck-typed, no hard dep, with fakes-based tests, an
  optional extra, and an index entry; full `pytest` + `ruff` + `clippy` green.
- A `recipes/` docs section exists, symptom-organized, every page ending in
  "What it does not do."
- The benchmark page shows real, reproducible numbers.
- A developer-experience pass is done: errors are actionable (with `.explain()`
  where messages are frozen), no block logs on its own, result objects read
  well, a `beacon doctor` command and an "error I don't understand" recipe
  exist, and every public symbol documents what it does *not* do.
- Four framework-docs drafts and a launch checklist exist under `docs/outreach/`,
  ready for the maintainer to submit.
- No gate violated; no existing output/error changed; "What NOT to build"
  respected.
- **Nothing committed, branched, PR'd, or published by you** — all changes left
  on `main` for the maintainer, with a short note of what you changed and what
  they need to run or submit.
