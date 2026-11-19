"""Provenance ledger: deterministic chain, tamper-evidence, offline verify."""

from __future__ import annotations

import asyncio
import dataclasses

import beacon
from beacon import Ledger, Pipeline, verify


def _summarize(s: str) -> dict:
    return {"text": s, "len": len(s)}


def _pipe() -> Pipeline:
    return Pipeline([str.strip, str.upper, _summarize])


def test_run_recorded_returns_output_and_one_record_per_block() -> None:
    rec = _pipe().run_recorded("  hello  ")
    assert rec.output == {"text": "HELLO", "len": 5}
    assert len(rec.ledger) == 3
    assert [r.op for r in rec.ledger] == ["str.strip", "str.upper", "_summarize"]
    assert rec.ledger.records[0].prev_hash == ""
    assert rec.ledger.root == rec.ledger.records[-1].record_hash


def test_root_is_deterministic() -> None:
    a = _pipe().run_recorded("  hello  ").ledger
    b = _pipe().run_recorded("  hello  ").ledger
    assert a.root == b.root
    # a different input gives a different root
    assert _pipe().run_recorded("  world  ").ledger.root != a.root


def test_root_matches_the_documented_chain_algorithm() -> None:
    # Pins the format and doubles as the cross-language spec: any binding that
    # computes this chain over beacon.hash_content must get the same root.
    rec = Pipeline([str.strip, str.upper]).run_recorded("  hi  ")
    params_none = beacon.hash_content(None, length=32)
    prev = ""
    for s in rec.ledger.records:
        expected = beacon.hash_content(
            ["v1", s.index, s.op, s.input_hash, params_none, s.output_hash, prev], length=32
        )
        assert s.record_hash == expected
        assert s.params_hash == params_none
        prev = expected
    assert rec.ledger.root == prev
    assert rec.ledger.version == "v1"


def test_verify_chain_only_passes_and_sets_reproduced_none() -> None:
    rec = _pipe().run_recorded("  hello  ")
    report = verify(rec.ledger)
    assert report.ok and report.chain_ok
    assert report.reproduced is None
    assert bool(report) is True
    assert report.failures == ()


def test_verify_reproduces_against_the_pipeline() -> None:
    p = _pipe()
    rec = p.run_recorded("  hello  ")
    report = verify(rec.ledger, "  hello  ", pipeline=p)
    assert report.ok and report.reproduced is True
    assert report.failures == ()


def test_verify_against_wrong_input_fails() -> None:
    p = _pipe()
    rec = p.run_recorded("  hello  ")
    report = verify(rec.ledger, "nope", pipeline=p)
    assert not report.ok
    assert report.reproduced is False
    assert any("input hash differs" in f for f in report.failures)


def test_tampered_record_is_detected() -> None:
    rec = _pipe().run_recorded("  hello  ")
    records = list(rec.ledger.records)
    records[1] = dataclasses.replace(records[1], output_hash="deadbeef")
    tampered = dataclasses.replace(rec.ledger, records=tuple(records))
    report = verify(tampered)
    assert not report.chain_ok and not report.ok
    assert any("tampered" in f for f in report.failures)


def test_broken_chain_link_is_detected() -> None:
    rec = _pipe().run_recorded("  hello  ")
    records = list(rec.ledger.records)
    records[2] = dataclasses.replace(records[2], prev_hash="0" * 32)
    broken = dataclasses.replace(rec.ledger, records=tuple(records))
    report = verify(broken)
    assert not report.chain_ok
    assert any("prev_hash does not chain" in f for f in report.failures)


def test_non_hashable_output_cannot_be_reproduced() -> None:
    p = Pipeline([str.strip, lambda s: object()])
    rec = p.run_recorded("  x  ")
    assert rec.ledger.records[1].output_hash is None
    report = verify(rec.ledger, "  x  ", pipeline=p)
    assert report.chain_ok  # the chain over a None hash is still valid
    assert report.reproduced is False
    assert any("not hashable" in f for f in report.failures)


def test_meta_is_sidecar_and_never_hashed() -> None:
    rec = _pipe().run_recorded("  hello  ")
    with_meta = rec.ledger.with_meta(run_id="abc", recorded_at="2026-11-16T00:00:00Z")
    # metadata does not change the root or verification
    assert with_meta.root == rec.ledger.root
    assert verify(with_meta).ok
    assert with_meta.as_dict()["meta"] == {"run_id": "abc", "recorded_at": "2026-11-16T00:00:00Z"}
    # a bare ledger carries no meta key
    assert "meta" not in rec.ledger.as_dict()


def test_dict_round_trip_preserves_root_and_verification() -> None:
    rec = _pipe().run_recorded("  hello  ")
    data = rec.ledger.as_dict()
    assert list(data) == ["version", "core_version", "root", "records"]
    assert set(data["records"][0]) == {
        "index", "op", "input_hash", "params_hash", "output_hash", "prev_hash", "record_hash"
    }
    restored = Ledger.from_dict(data)
    assert restored.root == rec.ledger.root
    assert verify(restored).ok


def test_core_version_is_recorded() -> None:
    rec = _pipe().run_recorded("  hello  ")
    assert rec.ledger.core_version == beacon.__version__
    report = verify(rec.ledger)
    assert report.core_version == beacon.__version__
    assert report.running_core_version == beacon.__version__


def test_report_as_dict() -> None:
    rec = _pipe().run_recorded("  hello  ")
    d = verify(rec.ledger).as_dict()
    assert d["ok"] is True and d["chain_ok"] is True and d["reproduced"] is None
    assert d["failures"] == []


def test_async_record_and_verify() -> None:
    async def main() -> None:
        p = _pipe()
        rec = await p.arun_recorded("  hello  ")
        assert rec.output == {"text": "HELLO", "len": 5}
        assert rec.ledger.root == p.run_recorded("  hello  ").ledger.root
        report = await beacon.aio.verify(rec.ledger)
        assert report.ok

    asyncio.run(main())
