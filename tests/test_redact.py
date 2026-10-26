from __future__ import annotations

import pytest

from beacon import detect_pii, redact
from beacon.snapshots import assert_snapshot
from conftest import outcome


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Email me at alice@example.com", "Email me at [REDACTED:email]"),
        ("Contact: John.Doe+tag@sub.example.co.uk.", "Contact: [REDACTED:email]."),
        ("Card: 4111-1111-1111-1111", "Card: [REDACTED:credit_card]"),
        ("Card: 4111 1111 1111 1111", "Card: [REDACTED:credit_card]"),
        ("Card 5500005555555559 ok", "Card [REDACTED:credit_card] ok"),
        ("Amex 378282246310005", "Amex [REDACTED:credit_card]"),
        ("Not a card: 1234-5678-9012-3456", "Not a card: 1234-5678-9012-3456"),
        ("SSN 123-45-6789", "SSN [REDACTED:ssn]"),
        ("SSN 000-12-3456 is invalid", "SSN 000-12-3456 is invalid"),
        ("SSN 666-12-3456 is invalid", "SSN 666-12-3456 is invalid"),
        ("SSN 900-12-3456 is invalid", "SSN 900-12-3456 is invalid"),
        ("Call 555-123-4567", "Call [REDACTED:phone]"),
        ("Call (555) 123-4567", "Call [REDACTED:phone]"),
        ("Call +1 (555) 123-4567", "Call [REDACTED:phone]"),
        ("Ring +44 20 7946 0958 today", "Ring [REDACTED:phone] today"),
        ("Call 555.123.4567", "Call [REDACTED:phone]"),
        ("Order 2024-01-15 shipped", "Order 2024-01-15 shipped"),
        ("Version 1.2.3 released", "Version 1.2.3 released"),
        ("Invoice #12345 paid", "Invoice #12345 paid"),
        ("Server 10.0.0.1 is up", "Server 10.0.0.1 is up"),  # IPs only in strict
        ("No PII here.", "No PII here."),
        ("", ""),
    ],
)
def test_default_policy(text: str, expected: str) -> None:
    assert redact(text) == expected


@pytest.mark.parametrize(
    "text,label",
    [
        ("sk-proj-abcdefghijklmnopqrstuvwxyz0123456789", "api_key"),
        ("sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123", "api_key"),
        ("ghp_" + "a" * 36, "api_key"),
        ("github_pat_" + "A1b2" * 6, "api_key"),
        ("xoxb-1234567890-abcdefghij", "api_key"),
        ("AIza" + "B" * 35, "api_key"),
        ("sk_live_" + "c" * 24, "api_key"),
        ("hf_" + "d" * 34, "api_key"),
        ("AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "jwt"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----", "private_key"),
        ("-----BEGIN PRIVATE KEY-----\nXYZ\n-----END PRIVATE KEY-----", "private_key"),
    ],
)
def test_secrets(text: str, label: str) -> None:
    assert redact(f"key: {text} end", policy="secrets") == f"key: [REDACTED:{label}] end"


def test_bearer_token_keeps_the_scheme() -> None:
    assert redact("Authorization: Bearer abc.def-ghi_jkl~mno+pqr/stu=") == "Authorization: Bearer [REDACTED:bearer_token]"


def test_strict_policy_adds_ip_addresses() -> None:
    assert redact("from 192.168.1.20 and 2001:db8::8a2e:370:7334", policy="strict") == (
        "from [REDACTED:ipv4] and [REDACTED:ipv6]"
    )
    assert redact("time 12:30:45, ratio 3:2, 999.1.1.1", policy="strict") == "time 12:30:45, ratio 3:2, 999.1.1.1"


def test_policies() -> None:
    text = "a@b.co 4111111111111111 sk-proj-abcdefghijklmnopqrstuvwxyz"
    assert redact(text, policy="pii") == "[REDACTED:email] [REDACTED:credit_card] sk-proj-abcdefghijklmnopqrstuvwxyz"
    assert redact(text, policy="secrets") == "a@b.co 4111111111111111 [REDACTED:api_key]"
    assert redact(text, policy="none") == text
    with pytest.raises(ValueError, match="policy must be"):
        redact(text, policy="paranoid")  # type: ignore[arg-type]


def test_exclude() -> None:
    assert redact("a@b.co 555-123-4567", exclude=["phone"]) == "[REDACTED:email] 555-123-4567"
    with pytest.raises(ValueError, match="unknown label in exclude"):
        redact("x", exclude=["mail"])
    with pytest.raises(TypeError):
        redact("x", exclude="phone")


def test_custom_patterns_and_terms() -> None:
    out = redact(
        "EMP-123456 works on Project Falcon (falcon) but not Falconry.",
        patterns={"employee_id": r"EMP-\d{6}"},
        terms={"codename": ["Project Falcon", "falcon"]},
    )
    assert out == "[REDACTED:employee_id] works on [REDACTED:codename] ([REDACTED:codename]) but not Falconry."


def test_custom_label_and_pattern_validation() -> None:
    with pytest.raises(ValueError, match="label"):
        redact("x", patterns={"Bad-Label": "x"})
    with pytest.raises(ValueError, match="invalid regular expression"):
        redact("x", patterns={"ok": "("})
    with pytest.raises(TypeError):
        redact("x", terms={"t": "single string"})  # type: ignore[dict-item]


def test_replacement_templates() -> None:
    assert redact("a@b.co", replacement="<{label}>") == "<email>"
    assert redact("a@b.co", replacement="{{{label}}}") == "{email}"
    hashed = redact("a@b.co and a@b.co and c@d.io", replacement="[{label}:{hash}]")
    first, second, third = hashed.split(" and ")
    assert first == second != third
    with pytest.raises(ValueError, match="replacement may only contain"):
        redact("a@b.co", replacement="{name}")


def test_overlaps_prefer_longest_then_priority() -> None:
    # The card number contains a phone-like run; the longer match wins.
    assert redact("4111-1111-1111-1111") == "[REDACTED:credit_card]"
    # An email inside a custom pattern match: the longer custom match wins.
    assert redact("id=user:alice@example.com", patterns={"user_ref": r"user:\S+"}) == "id=[REDACTED:user_ref]"


def test_detect_pii_offsets_are_code_points() -> None:
    text = "日本 alice@example.com と 555-123-4567"
    findings = detect_pii(text)
    assert findings == [
        {"label": "email", "start": 3, "end": 20, "text": "alice@example.com"},
        {"label": "phone", "start": 23, "end": 35, "text": "555-123-4567"},
    ]
    for f in findings:
        assert text[f["start"] : f["end"]] == f["text"]


def test_redaction_is_idempotent() -> None:
    text = "mail a@b.co, card 4111111111111111, key sk-proj-abcdefghijklmnopqrstuvwxyz"
    once = redact(text)
    assert redact(once) == once


def test_deterministic() -> None:
    text = "a@b.co 555-123-4567 " * 50
    assert len({redact(text) for _ in range(50)}) == 1


CORPUS = {
    "support_ticket": "Hi, I'm Jane (jane.doe@example.com, +1 415-555-0132). My card 4242 4242 4242 4242 was charged twice. SSN on file: 219-09-9999.",
    "log_line_with_secrets": "2026-10-25 INFO auth header='Bearer abcdefghijklmnopqrstuvwxyz012345' key=sk-proj-0123456789abcdefghijABCDEFGHIJ aws=AKIAIOSFODNN7EXAMPLE",
    "jwt_and_ip": "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhYmMifQ.c2lnbmF0dXJlX2hlcmU from 203.0.113.9",
    "private_key_block": "config:\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----\ndone",
    "near_misses": "Order 2024-01-15, v1.2.3, ticket #555123, 1234-5678-9012-3456, 000-12-3456, user@localhost",
    "unicode_context": "Écrivez à zoë@exemple.fr ou appelez le +33 1 23 45 67 89 — merci!",
    "custom_terms": "Project Falcon launches; falcon team; Falconry club.",
}


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_snapshot_corpus(case: str) -> None:
    text = CORPUS[case]
    terms = {"codename": ["Project Falcon", "falcon"]} if case == "custom_terms" else None
    result = {
        "redacted": outcome(redact, text, policy="strict", terms=terms),
        "findings": outcome(detect_pii, text, policy="strict", terms=terms),
    }
    assert_snapshot(f"redact/{case}", result, input=text)
