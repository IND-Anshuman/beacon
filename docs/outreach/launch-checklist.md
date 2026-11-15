# Launch checklist

What must be true before announcing beacon publicly. This is the **checklist, not
the act** — every publish, PR and post below is the maintainer's to make. See
[`docs/releasing.md`](../releasing.md) for the exact publish commands.

## ⚠️ Version first

The npm package `llm-beacon` is **already published at 1.0.0**. This Adoption
phase adds new, backward-compatible features — 8 Python framework adapters, the
Vercel AI SDK TypeScript adapter, the recipes docs and the benchmark page. Under
semver these are a **minor** release.

Before republishing anything already live, bump the version (suggested **1.1.0**)
in all three manifests and refresh the lockfiles, then add a `[1.1.0]` CHANGELOG
section:

- [ ] `Cargo.toml` `[workspace.package] version`
- [ ] `pyproject.toml` `[project] version`
- [ ] `crates/beacon-js/pkg/package.json` `version`
- [ ] `cargo check --workspace` (refreshes `Cargo.lock` and `crates/beacon-js/Cargo.lock`)
- [ ] `CHANGELOG.md` + `website/.../reference/changelog.mdx` — new `1.1.0` section

(If crates.io `beacon-core` and PyPI `llm-beacon` were never published at 1.0.0,
they can go out at 1.0.0 or 1.1.0 — just keep all three registries on the same
number.)

## Packages (maintainer publishes)

- [ ] **PyPI** `llm-beacon` — publish a GitHub Release; the `Release` workflow
      builds abi3 wheels + sdist and uploads via trusted publishing. First upload
      needs a PyPI pending publisher configured (see `docs/releasing.md`).
- [ ] **crates.io** `beacon-core` — `cargo publish -p beacon-core` (others are
      `publish = false`).
- [ ] **npm** `llm-beacon` — build with `wasm-bindgen` 0.2.130, then
      `npm publish` from `crates/beacon-js/pkg` (ships the new `./vercel`
      subpath export).
- [ ] Confirm names resolve after publish: `pip install llm-beacon`,
      `cargo add beacon-core`, `npm view llm-beacon`.

## Docs & site

- [ ] Docs site deployed and reachable (Vercel Git integration →
      <https://www.anshumanbuilds.dev/beacon/>).
- [ ] New pages live: `guarantees/overhead`, the `recipes/` section (16 pages).
- [ ] `website/public/` assets present and current: `llms.txt`, `og.png`,
      `robots.txt`, `favicon.svg`. ✅ (all present in repo)
- [ ] README / quickstart commands run as written against the published package.
- [ ] `og.png` renders correctly when a docs link is shared (Twitter/Slack/LinkedIn).

## Correctness gates (must be green)

- [ ] `pytest --beacon-snapshot check` — full suite, strict snapshots.
- [ ] `ruff check python tests examples benches`.
- [ ] `cargo clippy --all-targets` (default and `--no-default-features`), plus
      `beacon-js` clippy on the wasm target.
- [ ] `cargo fmt --check`.
- [ ] npm: `node crates/beacon-js/build.mjs`, then the Node smoke test and
      `vercel.test.mjs`; `tests/test_parity_js.py` (the cross-language corpus).
- [ ] `python benches/determinism_overhead.py` within budget.
- [ ] CI green on `main` (the `js` job guards the npm build + parity corpus).

## Outreach (maintainer submits, longest lead time)

- [ ] Review and submit the four framework-docs drafts in `docs/outreach/`
      (LangChain, LlamaIndex, Pydantic AI, DSPy), each matched to the target
      repo's contribution guide.
- [ ] Verify the compatibility notes still hold at submission (LangChain 1.x,
      DSPy 3.x, Pydantic AI, LlamaIndex versions).

## Announcement (maintainer's words, maintainer's accounts)

- [ ] Launch post(s) drafted and posted by the maintainer. Lead with the one
      claim the project can defend: **same input → byte-identical output,
      everywhere, forever** — and link the determinism and overhead pages as the
      evidence.
