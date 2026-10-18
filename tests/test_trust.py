"""Trust layer: claims vs verification, payment safety."""

import pytest

from contract.models import (
    Classification,
    Fact,
    FactKind,
    SourceSpan,
    VerificationStatus,
)
from engine.pipeline import LetterDecoderPipeline
from engine.trust import assess_trust, trust_warnings


def _amount_fact(label="Penalty amount", value="1200.00 INR"):
    return Fact(
        kind=FactKind.AMOUNT,
        label=label,
        raw_value=value,
        normalized_value=value,
        confidence=0.9,
        verified=True,
        source=SourceSpan(page=1, text=value),
        verification=VerificationStatus.SUPPORTED,
    )


def _deadline_fact(iso="2026-11-02"):
    return Fact(
        kind=FactKind.DATE,
        label="Payment deadline",
        raw_value="2 November 2026",
        normalized_value=iso,
        confidence=0.9,
        verified=True,
        source=SourceSpan(page=1, text="Payment deadline: 2 November 2026."),
        verification=VerificationStatus.SUPPORTED,
        role="payment_deadline",
    )


def _classification(sender=None, confidence=0.6, notice_type_id="xx_placeholder_notice"):
    return Classification(
        notice_type_id=notice_type_id,
        country="XX",
        language="en",
        sender=sender,
        confidence=confidence,
    )


SCAM_TEXT = (
    "You must transfer 9,999 in the next 2 hours or police will arrest you tonight. "
    "Pay only to UPI ID: urgent-clearance-000@demo. Do not call your bank or speak "
    "to anyone. This offer expires immediately."
)


def test_unverified_sender_flags_payment():
    trust = assess_trust(
        "Payment deadline: 2 November 2026. Pay the penalty.",
        [_amount_fact(), _deadline_fact()],
        _classification(sender="CITY OF NORTHBRIDGE"),
        {"id": "xx_placeholder_notice", "sender": "Unknown Sender"},
    )
    assert trust.sender_verified is False
    assert trust.verify_before_payment is True
    codes = {c for c, _ in trust_warnings(trust)}
    assert "sender_identity_unverified" in codes
    assert "verify_before_payment" in codes


def test_missing_payment_instructions_flagged():
    trust = assess_trust(
        "Payment deadline: 2 November 2026.",
        [_amount_fact(), _deadline_fact()],
        _classification(sender="CITY OF NORTHBRIDGE"),
        {"id": "xx_placeholder_notice", "sender": "Unknown Sender"},
    )
    assert trust.payment_instructions_present is False
    codes = {c for c, _ in trust_warnings(trust)}
    assert "missing_payment_instructions" in codes


def test_scam_pressure_detected():
    trust = assess_trust(
        SCAM_TEXT,
        [_amount_fact(label="Amount", value="9999.00 INR")],
        _classification(sender=None, confidence=0.0, notice_type_id="unknown"),
        {"id": "unknown"},
    )
    assert trust.scam_pressure is True
    assert trust.verify_before_payment is True
    assert trust.payment_instructions_present is True  # UPI ID is present
    codes = {c for c, _ in trust_warnings(trust)}
    assert "possible_scam_pressure" in codes


def test_informational_letter_not_payment_flagged():
    trust = assess_trust(
        "This letter confirms your address was updated. No payment is requested.",
        [],
        _classification(sender="HARBORLIGHT GENERAL INSURANCE"),
        {"id": "xx_placeholder_notice", "sender": "Unknown Sender"},
    )
    assert trust.verify_before_payment is False
    assert trust.payment_instructions_present is None
    assert trust_warnings(trust) == []


def test_verified_sender_no_verify_warning():
    trust = assess_trust(
        "Payment deadline: 2 November 2026. Pay by UPI.",
        [_amount_fact(), _deadline_fact()],
        _classification(sender="Revenue Office", confidence=0.9),
        {"id": "tax_notice", "sender": "Revenue Office"},
    )
    assert trust.sender_verified is True
    codes = {c for c, _ in trust_warnings(trust)}
    assert "sender_identity_unverified" not in codes
    assert trust.verify_before_payment is False


def test_verdict_never_imperative_pay_for_unverified():
    p = LetterDecoderPipeline()
    from contract.models import Deadline, DeadlineKind, Severity, SeverityLevel

    trust = assess_trust(
        "Payment deadline: 2 November 2026.",
        [_amount_fact(), _deadline_fact()],
        _classification(sender="CITY OF NORTHBRIDGE"),
        {"id": "xx_placeholder_notice", "sender": "Unknown Sender"},
    )
    deadline = Deadline(kind=DeadlineKind.PAYMENT, iso_date="2026-11-02", confidence=0.9)
    severity = Severity(level=SeverityLevel.ROUTINE)
    verdict = p._compute_verdict(
        [_amount_fact(), _deadline_fact()],
        _classification(sender="CITY OF NORTHBRIDGE"),
        deadline,
        severity,
        trust,
    )
    text = verdict.text.lower()
    assert "pay by" not in text
    assert "pay " not in text.split(".")[0]  # no imperative in first sentence
    assert "unverified" in text


def test_scam_severity_override():
    p = LetterDecoderPipeline()
    from contract.models import Classification

    trust = assess_trust(SCAM_TEXT, [_amount_fact(label="Amount")], None, {"id": "unknown"})
    severity = p._compute_severity(
        [], Classification(notice_type_id="unknown", country="XX", language="en", confidence=0.0),
        {"severity": "routine"}, trust,
    )
    assert severity.level.value == "see_professional"
    assert "verify" in severity.reason.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
