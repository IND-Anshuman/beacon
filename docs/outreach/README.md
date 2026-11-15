# Outreach drafts

These are **draft documentation pages** written for other projects' docs — "How
to use beacon with X" guides — plus the launch checklist. They are the
highest-leverage adoption channel: a short, genuinely useful page in a
framework's own docs reaches its users where they already are.

**Nothing here has been submitted.** Opening PRs into these projects is the
maintainer's call. Each draft is written in the target project's documentation
voice with a runnable minimal example, ready to adapt to that repo's structure
and contribution guidelines.

| Draft | Target | Where it likely fits |
| --- | --- | --- |
| [`langchain.md`](langchain.md) | LangChain | Integrations / "Providers" or "More" → output parsers |
| [`llamaindex.md`](llamaindex.md) | LlamaIndex | Module guides → Querying → Structured Outputs / Output Parsing |
| [`pydantic-ai.md`](pydantic-ai.md) | Pydantic AI | Output / validation docs (output validators) |
| [`dspy.md`](dspy.md) | DSPy | Tutorials / "Deployment" or Adapters |

Each page already corresponds to a **shipped, tested** adapter in
`beacon.integrations`, so every example runs against the current release.

Before submitting, per each project's contribution guide: match their page
front-matter/format, run their docs build, and keep the example minimal. Verify
the version compatibility notes (LangChain 1.x, DSPy 3.x, etc.) still hold at
submission time.

See also [`launch-checklist.md`](launch-checklist.md).
