"""Trust layer: whether it is safe to act on a letter's demands as written.

A document can state facts about itself (amounts, deadlines) without proving
who sent it. This module separates what the letter claims from what has been
verified, so the answer never tells the user to pay a claimed sender.
"""

from __future__ import annotations

import re

from contract.models import (
    Classification,
    Fact,
    FactKind,
    TrustAssessment,
    VerificationStatus,
)

# Where to pay, if the letter says so at all.
_PAYMENT_INSTRUCTION_PATTERNS = [
    r"\bupi\b",
    r"\bifsc\b",
    r"\biban\b",
    r"\bsort code\b",
    r"\baccount (?:no|number)\b",
    r"\ba/?c(?:count)?\s*(?:no|number)\b",
    r"\bqr code\b",
    r"\btransfer to\b",
    r"\bdeposit to\b",
    r"\bpayable at\b",
    r"\bcredit to\b",
    r"\bbank details\b",
]

# High-pressure / isolation tactics typical of scam demands.
_PRESSURE_PATTERNS = [
    r"\barrest\b",
    r"\btonight\b",
    r"\bwithin the next \d+\s*hours?\b",
    r"\bthe next \d+\s*hours?\b",
    r"\bdo not (?:call|contact|speak|tell)\b",
    r"\bexpires immediately\b",
    r"\bact immediately\b",
    r"\bimmediately or\b",
    r"\bfinal legal action\b",
    r"\bfailure to (?:pay|act) (?:immediately|now)\b",
]

_MONEY_DEMAND_LABELS = {"Amount due", "Penalty amount", "Tax amount"}


def assess_trust(
    text: str,
    facts: list[Fact],
    classification: Classification | None,
    notice_pack: dict | None,
) -> TrustAssessment:
    """Assess whether the letter's demands can be trusted as written."""
    text_lower = text.lower()

    sender_fact = next((f for f in facts if f.kind == FactKind.SENDER), None)
    sender_claimed = (classification.sender if classification and classification.sender else None) or (
        sender_fact.normalized_value if sender_fact else None
    )

    pack_sender = (notice_pack or {}).get("sender")
    pack_type_id = (notice_pack or {}).get("id")
    classification_ok = bool(
        classification
        and classification.notice_type_id != "unknown"
        and classification.confidence >= 0.5
        and pack_type_id
    )
    sender_verified = bool(
        classification_ok
        and pack_sender
        and sender_claimed
        and _names_match(pack_sender, sender_claimed)
    )

    payment_deadline_fact = next(
        (f for f in facts if f.role == "payment_deadline"), None
    )
    amount_fact = next(
        (f for f in facts if f.kind == FactKind.AMOUNT and f.verification != VerificationStatus.NOT_FOUND),
        None,
    )
    scam_pressure = _count_matches(text_lower, _PRESSURE_PATTERNS) >= 2
    payment_demand = bool(
        payment_deadline_fact
        or (
            amount_fact
            and (scam_pressure or amount_fact.label in _MONEY_DEMAND_LABELS)
        )
    )

    payment_instructions: bool | None = None
    if payment_demand:
        payment_instructions = any(
            re.search(p, text_lower) for p in _PAYMENT_INSTRUCTION_PATTERNS
        )

    reasons: list[str] = []
    if payment_demand and not sender_verified:
        reasons.append("The sender's identity could not be verified.")
    if payment_demand and payment_instructions is False:
        reasons.append("The letter does not say where or how to pay.")
    if scam_pressure:
        reasons.append("The letter uses high-pressure tactics.")

    verify_before_payment = bool(payment_demand and reasons)

    return TrustAssessment(
        sender_claimed=sender_claimed,
        sender_verified=sender_verified,
        payment_instructions_present=payment_instructions,
        verify_before_payment=verify_before_payment,
        scam_pressure=scam_pressure,
        reasons=reasons,
    )


def trust_warnings(trust: TrustAssessment) -> list[tuple[str, str]]:
    """Warnings derived from the trust assessment, as (code, message) pairs."""
    warnings: list[tuple[str, str]] = []

    if trust.verify_before_payment and not trust.sender_verified:
        who = trust.sender_claimed or "an unknown sender"
        warnings.append(
            (
                "sender_identity_unverified",
                f"This letter claims to be from {who}, but the sender could not "
                "be verified from the document alone.",
            )
        )
    if trust.verify_before_payment and trust.payment_instructions_present is False:
        warnings.append(
            (
                "missing_payment_instructions",
                "The letter demands payment but does not state where or how to pay.",
            )
        )
    if trust.scam_pressure:
        warnings.append(
            (
                "possible_scam_pressure",
                "This message uses high-pressure tactics (urgency, threats, or "
                "isolation). Treat its claims as unconfirmed.",
            )
        )
    if trust.verify_before_payment:
        warnings.append(
            (
                "verify_before_payment",
                "Verify this letter through an independently obtained official "
                "channel before paying, replying with details, or sharing documents.",
            )
        )

    return warnings


def _names_match(pack_sender: str, claimed: str) -> bool:
    a = " ".join(pack_sender.lower().split())
    b = " ".join(claimed.lower().split())
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _count_matches(text: str, patterns: list[str]) -> int:
    return sum(1 for p in patterns if re.search(p, text))
