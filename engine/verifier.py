"""Verifier: check LLM output against deterministic facts."""

from __future__ import annotations

from contract.models import Answer, Fact, Warning


async def verify_answer(answer: Answer, deterministic_facts: list[Fact]) -> list[Warning]:
    """Verify LLM output against deterministic facts."""
    warnings = []

    # Create lookup maps
    date_facts = {f.normalized_value: f for f in deterministic_facts if f.kind.value == "date"}
    amount_facts = {f.normalized_value: f for f in deterministic_facts if f.kind.value == "amount"}

    # Check dates in explanation and steps
    _check_dates_in_text(answer, date_facts, warnings)
    _check_amounts_in_text(answer, amount_facts, warnings)

    # Check deadline consistency
    if answer.deadline and answer.deadline.iso_date:
        if answer.deadline.iso_date not in date_facts:
            warnings.append(
                Warning(
                    code="verifier_mismatch",
                    message=f"Deadline date {answer.deadline.iso_date} not found in deterministic extraction",
                )
            )

    # Check for missing deadline warning
    if not answer.deadline or not answer.deadline.iso_date:
        # Check if any date facts exist but weren't used as deadline
        if date_facts:
            warnings.append(
                Warning(
                    code="no_deadline_found",
                    message="No deadline detected in this letter. Dates were found but none matched deadline criteria.",
                )
            )

    return warnings


def _check_dates_in_text(answer: Answer, date_facts: dict, warnings: list[Warning]) -> None:
    """Check if dates mentioned in LLM output exist in deterministic facts."""
    # Check explanation
    texts_to_check = []
    if answer.explanation:
        texts_to_check.append(answer.explanation.simple)
        texts_to_check.append(answer.explanation.detailed)

    # Check steps
    for step in answer.steps:
        texts_to_check.append(step.text)
        if step.detail:
            texts_to_check.append(step.detail)

    # Check verdict
    if answer.verdict:
        texts_to_check.append(answer.verdict.text)

    import re

    # Look for date patterns in text
    date_patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",  # ISO
        r"\b(\d{1,2}[\s/-]\d{1,2}[\s/-]\d{2,4})\b",
        r"\b(\d{1,2}\s+\w+\s+\d{2,4})\b",
    ]

    for text in texts_to_check:
        for pattern in date_patterns:
            for match in re.finditer(pattern, text):
                date_str = match.group(1)
                # Try to normalize
                from dateparser import parse

                parsed = parse(date_str, settings={"PREFER_DATES_FROM": "future"})
                if parsed:
                    iso_date = parsed.strftime("%Y-%m-%d")
                    if iso_date not in date_facts:
                        warnings.append(
                            Warning(
                                code="verifier_mismatch",
                                message=f"Date '{date_str}' in explanation not found in deterministic facts",
                            )
                        )


def _check_amounts_in_text(answer: Answer, amount_facts: dict, warnings: list[Warning]) -> None:
    """Check if amounts mentioned in LLM output exist in deterministic facts."""
    texts_to_check = []
    if answer.explanation:
        texts_to_check.append(answer.explanation.simple)
        texts_to_check.append(answer.explanation.detailed)

    for step in answer.steps:
        texts_to_check.append(step.text)
        if step.detail:
            texts_to_check.append(step.detail)

    if answer.verdict:
        texts_to_check.append(answer.verdict.text)

    import re

    # Look for amount patterns (Indian currency)
    amount_patterns = [
        r"[₹Rs\.]*\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
        r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:INR|rupees?)",
    ]

    for text in texts_to_check:
        for pattern in amount_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                amount_str = match.group(1).replace(",", "")
                try:
                    normalized = f"{float(amount_str):.2f} INR"
                    if normalized not in amount_facts:
                        warnings.append(
                            Warning(
                                code="verifier_mismatch",
                                message=f"Amount '{match.group(0)}' in explanation not found in deterministic facts",
                            )
                        )
                except ValueError:
                    pass
