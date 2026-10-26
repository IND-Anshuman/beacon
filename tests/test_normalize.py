from __future__ import annotations

import pytest

from beacon import UNICODE_VERSION, normalize
from beacon.snapshots import assert_snapshot
from conftest import outcome


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hello   World\n\n", "Hello World"),
        ("Hello\tWorld", "Hello World"),
        ("  leading and trailing  ", "leading and trailing"),
        ("a\r\nb\rc\nd", "a b c d"),
        ("non breaking　ideographic", "non breaking ideographic"),
        ("zero​width﻿⁠joined", "zerowidthjoined"),
        ("bell\x07 and null\x00", "bell and null"),
        ("ﬁ ligature", "fi ligature"),
        ("fullｗidth", "fullwidth"),
        ("x²", "x2"),
        ("Café", "Café"),
        ("", ""),
        ("   ", ""),
        ("é", "é"),  # NFKC composes
        ("👨‍👩‍👧", "👨‍👩‍👧"),  # ZWJ sequences are kept
        ("שלום  עולם", "שלום עולם"),
        ("مرحبا‏بالعالم", "مرحبا‏بالعالم"),  # bidi marks are kept
    ],
)
def test_defaults(text: str, expected: str) -> None:
    assert normalize(text) == expected


def test_strip_accents() -> None:
    assert normalize("Café", strip_accents=True) == "Cafe"
    assert normalize("Ångström naïve façade", strip_accents=True) == "Angstrom naive facade"


def test_lowercase_is_locale_independent() -> None:
    assert normalize("HELLO Wörld", lowercase=True) == "hello wörld"
    assert normalize("İ", lowercase=True) == "i̇"  # Unicode default mapping, not Turkish
    assert normalize("ΣΑΣ", lowercase=True) == "σας"  # final sigma


def test_forms() -> None:
    assert normalize("é", form="NFD") == "é"
    assert normalize("é", form="NFD") == "é"
    assert normalize("ﬁ", form="NFC") == "ﬁ"
    assert normalize("ﬁ", form="NFKD") == "fi"
    assert normalize("ﬁ", form=None) == "ﬁ"
    assert normalize("ﬁ", form="nfkc") == "fi"  # type: ignore[arg-type]


def test_invalid_form() -> None:
    with pytest.raises(ValueError, match="form must be one of"):
        normalize("x", form="NFX")  # type: ignore[arg-type]


def test_preserve_newlines() -> None:
    assert normalize("a  b\n\n\n  c \r\n d", preserve_newlines=True) == "a b\nc\nd"


def test_switches_off() -> None:
    raw = "  a​ \x07 b  "
    assert normalize(raw, collapse_whitespace=False, strip=False, remove_control=False, remove_zero_width=False) == raw
    assert normalize("a  b", collapse_whitespace=False) == "a  b"
    assert normalize("  a  ", strip=False) == " a "


def test_idempotent() -> None:
    for text in ["Hello   World", "Café ﬁ​", "a\r\n\r\nb", "ΣΑΣ İ"]:
        for opts in [{}, {"lowercase": True, "strip_accents": True}, {"preserve_newlines": True}]:
            once = normalize(text, **opts)  # type: ignore[arg-type]
            assert normalize(once, **opts) == once  # type: ignore[arg-type]


def test_unicode_version_is_exposed() -> None:
    assert UNICODE_VERSION.count(".") == 2


def test_type_check() -> None:
    with pytest.raises(TypeError):
        normalize(None)  # type: ignore[arg-type]


CORPUS = {
    "llm_output_spacing": ("  The answer is:\n\n\n   42.  \n", {}),
    "smart_quotes_and_dashes": ("“Quoted” — dash – en ‘single’", {}),
    "accents_lowercase": ("Crème Brûlée À LA CARTE", {"strip_accents": True, "lowercase": True}),
    "compatibility_chars": ("①②③ ﬀ ㎏ Ⅻ ½", {}),
    "zero_width_soup": ("in​visible﻿ ⁠chars", {}),
    "emoji_sequences": ("👍🏽 🏳️‍🌈 👨‍💻", {}),
    "rtl_mixed": ("Hello שלום مرحبا 123", {}),
    "paragraphs": ("Para one.\n\n\nPara two.\r\n\r\nPara three.", {"preserve_newlines": True}),
    "no_normalization_form": ("ﬁ ½", {"form": None}),
    "invalid_form": ("x", {"form": "NFZ"}),
}


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_snapshot_corpus(case: str) -> None:
    text, opts = CORPUS[case]
    assert_snapshot(f"normalize/{case}", outcome(normalize, text, **opts), input={"text": text, "options": opts})
