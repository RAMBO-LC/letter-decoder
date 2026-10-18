"""Tests for deterministic fact extraction."""

import pytest

from engine.deterministic_extract import extract_facts


@pytest.mark.asyncio
async def test_extract_dates():
    text = "Payment due by 15 Nov 2024. Please respond by 30/11/2024."
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    date_facts = [f for f in facts if f.kind.value == "date"]
    assert len(date_facts) >= 1
    assert any(f.normalized_value == "2024-11-15" for f in date_facts)


@pytest.mark.asyncio
async def test_extract_amounts():
    text = "Amount: ₹2,500. Total due Rs. 5,000.00"
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    amount_facts = [f for f in facts if f.kind.value == "amount"]
    assert len(amount_facts) >= 1
    assert any("2500" in f.normalized_value for f in amount_facts)


@pytest.mark.asyncio
async def test_extract_references():
    text = "Ref: GST/2024/11/0042. Reference No: IT/2024/10/0156"
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    ref_facts = [f for f in facts if f.kind.value == "reference"]
    assert len(ref_facts) >= 1
    assert any("GST/2024/11/0042" in f.normalized_value for f in ref_facts)


@pytest.mark.asyncio
async def test_source_span_attached():
    """Every fact should have a source span."""
    text = "Due by 15 Nov 2024. Amount ₹2,500."
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    for fact in facts:
        assert fact.source is not None
        assert fact.source.page == 1
        assert fact.source.text != ""


@pytest.mark.asyncio
async def test_confidence_range():
    """Confidence should be between 0 and 1."""
    text = "Due by 15 Nov 2024."
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    for fact in facts:
        assert 0.0 <= fact.confidence <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
