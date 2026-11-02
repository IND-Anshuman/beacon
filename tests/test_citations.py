from __future__ import annotations

import pytest

from beacon import extract_citations
from beacon.snapshots import assert_snapshot


def test_numeric_markers() -> None:
    c = extract_citations("See [1] and [2, 3] and [4-6].")
    assert [(x["kind"], x["ref"], x["text"]) for x in c] == [
        ("numeric", "1", "[1]"),
        ("numeric", "2, 3", "[2, 3]"),
        ("numeric", "4-6", "[4-6]"),
    ]


def test_footnotes() -> None:
    c = extract_citations("As shown[^note1] and[^2].")
    assert [(x["kind"], x["ref"]) for x in c] == [("footnote", "note1"), ("footnote", "2")]


def test_urls_trim_punctuation() -> None:
    c = extract_citations("See https://example.com/a, and (https://example.org/b).")
    assert c[0]["text"] == "https://example.com/a"
    assert c[0]["ref"] == "https://example.com/a"
    assert c[1]["text"] == "https://example.org/b"


def test_kinds_filter() -> None:
    text = "[1] [^a] https://x.io"
    assert all(x["kind"] == "numeric" for x in extract_citations(text, kinds=["numeric"]))
    assert len(extract_citations(text, kinds=["url"])) == 1
    assert extract_citations(text, kinds=[]) == []


def test_order_and_code_point_offsets() -> None:
    c = extract_citations("é https://a.io then [1]")
    assert [x["kind"] for x in c] == ["url", "numeric"]
    # The marker starts after the multi-byte 'é'; offsets are code points.
    assert c[1]["text"] == "[1]"
    assert c[1]["start"] == len("é https://a.io then ")


def test_invalid_kind_raises() -> None:
    with pytest.raises(ValueError):
        extract_citations("x", kinds=["bogus"])


def test_kinds_str_raises() -> None:
    with pytest.raises(TypeError):
        extract_citations("x", kinds="numeric")  # type: ignore[arg-type]


def test_non_str_text_raises() -> None:
    with pytest.raises(TypeError):
        extract_citations(123)  # type: ignore[arg-type]


def test_plain_text_has_no_citations() -> None:
    assert extract_citations("ordinary prose, nothing to cite") == []


CORPUS = {
    "numeric_single": "The study [1] found this.",
    "numeric_list": "Multiple sources [1, 2, 3] agree.",
    "numeric_range": "See references [4-6] for details.",
    "footnote": "A claim[^1] with a footnote[^longer-id].",
    "url_bare": "Read more at https://example.com/path.",
    "url_in_parens": "(see https://example.org/x) for context",
    "mixed": "Per [1] and[^a], see https://docs.example.com/guide#top.",
    "none": "no citations here at all",
}


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_snapshot_corpus(case: str) -> None:
    text = CORPUS[case]
    assert_snapshot(f"extract_citations/{case}", extract_citations(text), input={"text": text})
