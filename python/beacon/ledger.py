"""Deterministic provenance ledger: a tamper-evident record of what a pipeline
did, plus an offline :func:`verify` that re-runs it to *prove* the outputs.

The ledger is a hash chain. Each record commits to the format version, its
index, the op name, the input hash, the params hash, the output hash and the
*previous* record's hash, all through :func:`hash_content`. Altering any record
changes its ``record_hash`` and breaks every link after it, so tampering is
detectable offline; re-running the same blocks on the same input reproduces
every output hash, which is a real proof — no model, no network.

Everything hashed here is deterministic. Wall-clock time, host and any other
non-reproducible data live only in :attr:`Ledger.meta`, which no hash covers and
which never affects verification. The chain algorithm is fully specified so a
binding in another language can reproduce byte-identical roots from the same
:func:`hash_content`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence

from ._api import hash_content
from ._beacon_native import VERSION as CORE_VERSION

if TYPE_CHECKING:
    from ._blocks import StepRecord

__all__ = [
    "LEDGER_FORMAT",
    "LedgerRecord",
    "Ledger",
    "RecordedResult",
    "VerifyReport",
    "build_ledger",
    "verify",
]

#: Ledger wire-format version. Part of the hash, so a bump invalidates old roots.
LEDGER_FORMAT = "v1"
_CHAIN_HASH_LEN = 32
#: Hash used for a record with no distinct params (the Pipeline path folds a
#: block's params into the op itself). A fixed, deterministic constant.
_PARAMS_NONE = hash_content(None, length=_CHAIN_HASH_LEN)


def _chain_hash(
    version: str,
    index: int,
    op: str,
    input_hash: Optional[str],
    params_hash: str,
    output_hash: Optional[str],
    prev_hash: str,
) -> str:
    return hash_content(
        [version, index, op, input_hash, params_hash, output_hash, prev_hash],
        length=_CHAIN_HASH_LEN,
    )


@dataclass(frozen=True)
class LedgerRecord:
    """One block run in the chain.

    ``input_hash``/``output_hash`` are :func:`hash_content` digests (or ``None``
    when the value was not hashable JSON-like data). ``record_hash`` commits to
    every field above plus ``prev_hash``; ``prev_hash`` is the previous record's
    ``record_hash`` (``""`` for the first).
    """

    index: int
    op: str
    input_hash: Optional[str]
    params_hash: str
    output_hash: Optional[str]
    prev_hash: str
    record_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "op": self.op,
            "input_hash": self.input_hash,
            "params_hash": self.params_hash,
            "output_hash": self.output_hash,
            "prev_hash": self.prev_hash,
            "record_hash": self.record_hash,
        }


@dataclass(frozen=True)
class Ledger:
    """An append-only chain of :class:`LedgerRecord`.

    :attr:`root` is the last record's ``record_hash`` — a byte-identical
    fingerprint of the whole run. :attr:`meta` is free-form sidecar data
    (timestamps, host, run id) that is **never hashed** and never affects
    verification; attach it deliberately with :meth:`with_meta`.
    """

    records: tuple[LedgerRecord, ...] = ()
    core_version: str = CORE_VERSION
    version: str = LEDGER_FORMAT
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def root(self) -> str:
        return self.records[-1].record_hash if self.records else ""

    def with_meta(self, **meta: Any) -> "Ledger":
        """A copy with extra sidecar metadata merged in. Does not change any
        hash or the root — metadata lives outside the verified content."""
        return replace(self, meta={**self.meta, **meta})

    def as_dict(self) -> dict[str, Any]:
        """A JSON-friendly dict. ``meta``, when present, is sidecar only."""
        out: dict[str, Any] = {
            "version": self.version,
            "core_version": self.core_version,
            "root": self.root,
            "records": [r.as_dict() for r in self.records],
        }
        if self.meta:
            out["meta"] = dict(self.meta)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Ledger":
        """Rebuild a ledger from :meth:`as_dict` output (e.g. loaded from disk)."""
        records = tuple(
            LedgerRecord(
                index=r["index"],
                op=r["op"],
                input_hash=r.get("input_hash"),
                params_hash=r["params_hash"],
                output_hash=r.get("output_hash"),
                prev_hash=r["prev_hash"],
                record_hash=r["record_hash"],
            )
            for r in data.get("records", ())
        )
        return cls(
            records=records,
            core_version=data.get("core_version", ""),
            version=data.get("version", LEDGER_FORMAT),
            meta=dict(data.get("meta", {})),
        )

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __repr__(self) -> str:
        if not self.records:
            return "Ledger(empty)"
        return f"Ledger(records={len(self.records)}, core={self.core_version!r}, root={self.root[:12]}…)"


@dataclass(frozen=True)
class RecordedResult:
    """What :meth:`Pipeline.run_recorded` returns: the output and its ledger."""

    output: Any
    ledger: Ledger


@dataclass(frozen=True)
class VerifyReport:
    """The result of :func:`verify`. Truthy when the ledger holds up.

    ``chain_ok`` is tamper-evidence (every record hashes to its contents and
    links to the previous). ``reproduced`` is ``True``/``False`` when a pipeline
    and inputs were given to re-run, else ``None``. ``failures`` names every
    problem, in order.
    """

    ok: bool
    chain_ok: bool
    reproduced: Optional[bool]
    core_version: str
    running_core_version: str
    failures: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ok

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "chain_ok": self.chain_ok,
            "reproduced": self.reproduced,
            "core_version": self.core_version,
            "running_core_version": self.running_core_version,
            "failures": list(self.failures),
        }


def build_ledger(steps: "Sequence[StepRecord]", *, core_version: str = CORE_VERSION) -> Ledger:
    """Chain a sequence of trace steps (from ``run_traced``) into a ledger."""
    records: list[LedgerRecord] = []
    prev = ""
    for s in steps:
        record_hash = _chain_hash(LEDGER_FORMAT, s.index, s.block, s.input_hash, _PARAMS_NONE, s.output_hash, prev)
        records.append(LedgerRecord(s.index, s.block, s.input_hash, _PARAMS_NONE, s.output_hash, prev, record_hash))
        prev = record_hash
    return Ledger(records=tuple(records), core_version=core_version)


def _check_chain(ledger: Ledger) -> list[str]:
    failures: list[str] = []
    prev = ""
    for i, r in enumerate(ledger.records):
        if r.index != i:
            failures.append(f"record {i}: index is {r.index}, expected {i}")
        if r.prev_hash != prev:
            failures.append(f"record {i}: prev_hash does not chain to record {i - 1}")
        expected = _chain_hash(ledger.version, r.index, r.op, r.input_hash, r.params_hash, r.output_hash, r.prev_hash)
        if r.record_hash != expected:
            failures.append(f"record {i} ({r.op}): record_hash does not match its contents (tampered)")
        prev = r.record_hash
    return failures


def verify(ledger: Ledger, inputs: Any = None, *, pipeline: Any = None) -> VerifyReport:
    """Verify a ledger offline.

    Always checks chain integrity (tamper-evidence) — no model, no network. When
    ``pipeline`` and ``inputs`` are given, also re-runs the pipeline on those
    inputs and confirms every op, input hash and output hash matches, proving the
    recorded run is reproducible.

    Args:
        ledger: the ledger to verify.
        inputs: the input the pipeline was originally run on (only used when
            ``pipeline`` is given).
        pipeline: the :class:`Pipeline` that produced the ledger, to re-run.

    Returns a :class:`VerifyReport`; it is truthy when the ledger holds up.
    """
    failures = _check_chain(ledger)
    chain_ok = not failures
    reproduced: Optional[bool] = None

    if pipeline is not None:
        reproduced = True
        fresh = pipeline.run_recorded(inputs).ledger
        if len(fresh.records) != len(ledger.records):
            failures.append(f"re-run produced {len(fresh.records)} steps, the ledger has {len(ledger.records)}")
            reproduced = False
        for a, b in zip(ledger.records, fresh.records, strict=False):
            if a.op != b.op:
                failures.append(f"step {a.index}: op changed {a.op!r} -> {b.op!r}")
                reproduced = False
            if a.input_hash != b.input_hash:
                failures.append(f"step {a.index} ({a.op}): input hash differs from the ledger")
                reproduced = False
            if a.output_hash is None or b.output_hash is None:
                failures.append(f"step {a.index} ({a.op}): output is not hashable; cannot verify reproduction")
                reproduced = False
            elif a.output_hash != b.output_hash:
                failures.append(f"step {a.index} ({a.op}): output hash mismatch (not reproduced)")
                reproduced = False

    ok = chain_ok and (reproduced is not False)
    return VerifyReport(
        ok=ok,
        chain_ok=chain_ok,
        reproduced=reproduced,
        core_version=ledger.core_version,
        running_core_version=CORE_VERSION,
        failures=tuple(failures),
    )
