"""Evidence-based verification: facts and generated text against the source."""

import pytest

from contract.models import (
    Answer,
    AnswerStatus,
    BigPrint,
    Deadline,
    DeadlineKind,
    Explanation,
    Fact,
    FactKind,
    SourceSpan,
    Step,
    VerificationStatus,
    Verdict,
)
from engine.deterministic_extract import extract_facts
from engine.verifier import verify_answer


def _fact(kind, label, raw, norm, verified=True, role=None):
    return Fact(
        kind=kind,
        label=label,
        raw_value=raw,
        normalized_value=norm,
        confidence=0.9,
        verified=verified,
        source=SourceSpan(page=1, text=raw),
        verification=VerificationStatus.SUPPORTED if verified else VerificationStatus.UNCERTAIN,
        role=role,
    )


def _answer(**kwargs):
    defaults = dict(id="t", status=AnswerStatus.READY)
    defaults.update(kwargs)
    return Answer(**defaults)


@pytest.mark.asyncio
async def test_supported_fact_marks_verified():
    """A fact is only verified when its value exists in the source."""
    text = "Payment deadline: 20 October 2026."
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    date_facts = [f for f in facts if f.kind == FactKind.DATE]
    assert date_facts
    for f in date_facts:
        assert f.verification == VerificationStatus.SUPPORTED
        assert f.verified is True


@pytest.mark.asyncio
async def test_unsupported_fact_is_not_verified():
    fact = Fact(
        kind=FactKind.DATE,
        label="Due date",
        raw_value="31 Dec 2099",
        normalized_value="2099-12-31",
        confidence=0.9,
        source=SourceSpan(page=1, text="31 Dec 2099"),
        verification=VerificationStatus.NOT_FOUND,
    )
    # NOT_FOUND forces verified=False via the model validator
    assert fact.verified is False


@pytest.mark.asyncio
async def test_explanation_date_outside_source_flagged():
    facts = [
        _fact(FactKind.DATE, "Payment deadline", "2 November 2026", "2026-11-02", role="payment_deadline")
    ]
    answer = _answer(
        deadline=Deadline(kind=DeadlineKind.PAYMENT, iso_date="2026-11-02", confidence=0.9),
        explanation=Explanation(simple="Pay by 31 December 2026.", detailed="Due 31 Dec 2026."),
    )
    warnings = await verify_answer(answer, facts)
    codes = {w.code for w in warnings}
    assert "unsupported_date" in codes


@pytest.mark.asyncio
async def test_explanation_dates_inside_source_pass():
    facts = [
        _fact(FactKind.DATE, "Payment deadline", "2 November 2026", "2026-11-02", role="payment_deadline")
    ]
    answer = _answer(
        deadline=Deadline(kind=DeadlineKind.PAYMENT, iso_date="2026-11-02", confidence=0.9),
        explanation=Explanation(
            simple="The payment deadline is 2 November 2026.",
            detailed="Payment of the amount is due by 2 November 2026.",
        ),
        verdict=Verdict(text="Pay attention by 2026-11-02."),
    )
    warnings = await verify_answer(answer, facts)
    assert "unsupported_date" not in {w.code for w in warnings}


@pytest.mark.asyncio
async def test_bare_digits_not_treated_as_amounts():
    """'12 months' / '90 days' fragments must never flag amount mismatches."""
    facts = [_fact(FactKind.AMOUNT, "Penalty amount", "Rs 1,200", "1200.00 INR")]
    answer = _answer(
        explanation=Explanation(
            simple="The letter mentions 12 months and section 90 of the process.",
            detailed="No money figure appears here at all.",
        )
    )
    warnings = await verify_answer(answer, facts)
    assert "unsupported_amount" not in {w.code for w in warnings}


@pytest.mark.asyncio
async def test_currency_amount_outside_source_flagged():
    facts = [_fact(FactKind.AMOUNT, "Penalty amount", "Rs 1,200", "1200.00 INR")]
    answer = _answer(
        explanation=Explanation(simple="You must also pay Rs 500.00 INR.", detailed="")
    )
    warnings = await verify_answer(answer, facts)
    assert "unsupported_amount" in {w.code for w in warnings}


@pytest.mark.asyncio
async def test_supported_amount_in_verdict_passes():
    facts = [_fact(FactKind.AMOUNT, "Penalty amount", "Rs 1,200", "1200.00 INR")]
    answer = _answer(
        verdict=Verdict(text="A demand for 1200.00 INR was found. Verify before paying.")
    )
    warnings = await verify_answer(answer, facts)
    assert "unsupported_amount" not in {w.code for w in warnings}


@pytest.mark.asyncio
async def test_conflicting_deadline_roles_warn():
    facts = [
        _fact(FactKind.DATE, "Response deadline", "28 October 2026", "2026-10-28", role="response_deadline"),
        _fact(FactKind.DATE, "Response deadline", "18 October 2026", "2026-10-18", role="response_deadline"),
    ]
    answer = _answer(deadline=Deadline(kind=DeadlineKind.RESPONSE, iso_date="2026-10-18", confidence=0.4))
    warnings = await verify_answer(answer, facts)
    conflict = [w for w in warnings if w.code == "conflicting_deadlines"]
    assert conflict
    assert "2026-10-18" in conflict[0].message and "2026-10-28" in conflict[0].message


@pytest.mark.asyncio
async def test_payment_and_appeal_are_not_conflicting():
    facts = [
        _fact(FactKind.DATE, "Payment deadline", "20 October 2026", "2026-10-20", role="payment_deadline"),
        _fact(FactKind.DATE, "Appeal deadline", "27 October 2026", "2026-10-27", role="appeal_deadline"),
    ]
    answer = _answer(deadline=Deadline(kind=DeadlineKind.PAYMENT, iso_date="2026-10-20", confidence=0.9))
    warnings = await verify_answer(answer, facts)
    assert "conflicting_deadlines" not in {w.code for w in warnings}


@pytest.mark.asyncio
async def test_deadline_unsupported_flagged():
    facts = [_fact(FactKind.DATE, "Issue date", "12 October 2026", "2026-10-12", role="issue")]
    answer = _answer(deadline=Deadline(kind=DeadlineKind.PAYMENT, iso_date="2026-11-02", confidence=0.9))
    warnings = await verify_answer(answer, facts)
    assert "unsupported_deadline" in {w.code for w in warnings}


@pytest.mark.asyncio
async def test_warnings_deduplicated():
    facts = [_fact(FactKind.DATE, "Due date", "2 November 2026", "2026-11-02", role="payment_deadline")]
    answer = _answer(
        deadline=Deadline(kind=DeadlineKind.PAYMENT, iso_date="2026-11-02", confidence=0.9),
        explanation=Explanation(simple="Due 31 December 2026.", detailed="Again: 31 Dec 2026."),
        steps=[Step(text="Act by 31 December 2026")],
        big_print=BigPrint(lines=["DUE 31 DEC 2026"]),
    )
    warnings = await verify_answer(answer, facts)
    date_warnings = [w for w in warnings if w.code == "unsupported_date"]
    # Same missing date from different fields may repeat; dedupe is by message.
    messages = [w.message for w in date_warnings]
    assert len(messages) == len(set(messages))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
