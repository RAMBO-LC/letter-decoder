"""Date semantic roles: every date is classified from its own sentence."""

import pytest

from engine.deterministic_extract import extract_facts
from engine.pipeline import LetterDecoderPipeline

# Synthetic fixture mirroring the user's NMP-TEST-2048 spec letter.
SPEC_LETTER = """MUNICIPAL NOTICE
Notice reference: NMP-TEST-2048
This notice was issued on 6 October 2026.
The incident occurred on 4 October 2026.
Payment deadline: 20 October 2026.
You may appeal by 27 October 2026.
For your information, the next statement will be sent on 2 November 2026.
A penalty of I1,200 is payable.
"""


@pytest.mark.asyncio
async def test_date_roles_separated():
    pages = [{"page_num": 1, "text": SPEC_LETTER, "bbox_data": []}]
    facts = await extract_facts(SPEC_LETTER, pages)
    by_role = {
        f.role: f.normalized_value for f in facts if f.kind.value == "date"
    }
    assert by_role["issue"] == "2026-10-06"
    assert by_role["incident"] == "2026-10-04"
    assert by_role["payment_deadline"] == "2026-10-20"
    assert by_role["appeal_deadline"] == "2026-10-27"
    assert by_role["informational"] == "2026-11-02"


@pytest.mark.asyncio
async def test_issue_date_not_used_as_deadline():
    """The issue date must never win the deadline slot."""
    pages = [{"page_num": 1, "text": SPEC_LETTER, "bbox_data": []}]
    facts = await extract_facts(SPEC_LETTER, pages)
    deadline = LetterDecoderPipeline()._compute_deadline(facts, {})
    assert deadline.kind.value == "payment"
    assert deadline.iso_date == "2026-10-20"


@pytest.mark.asyncio
async def test_informational_only_no_deadline():
    text = """HARBORLIGHT GENERAL INSURANCE
Date: 14 October 2026
This letter confirms that your policy contact address was updated successfully on 13 October 2026. No payment is requested."""
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    deadline = LetterDecoderPipeline()._compute_deadline(facts, {})
    assert deadline.iso_date is None
    assert deadline.kind.value == "unknown"


@pytest.mark.asyncio
async def test_conflicting_response_dates_pick_earliest_low_confidence():
    text = """REVENUE OFFICE
Letter date: 5 October 2026
Response deadline: 28 October 2026.
Footer: "Please respond by 18 October 2026."
"""
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    deadline = LetterDecoderPipeline()._compute_deadline(facts, {})
    assert deadline.kind.value == "response"
    assert deadline.iso_date == "2026-10-18"
    assert deadline.confidence <= 0.5


@pytest.mark.asyncio
async def test_ambiguous_fragment_yields_no_date():
    """No fabricated dates from OCR fragments like '1?/10/2026'."""
    text = "Date: 1?/10/2026\nYour application has been placed on hold."
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    assert [f for f in facts if f.kind.value == "date"] == []


@pytest.mark.asyncio
async def test_all_dates_source_supported():
    pages = [{"page_num": 1, "text": SPEC_LETTER, "bbox_data": []}]
    facts = await extract_facts(SPEC_LETTER, pages)
    for f in facts:
        if f.kind.value == "date":
            assert f.verification.value == "SUPPORTED"
            assert f.verified is True
            assert f.source.text  # quotes its sentence


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
