"""Reference extraction: structured IDs only, no digit fragments."""

import pytest

from engine.deterministic_extract import extract_facts


async def _refs(text: str) -> list[str]:
    pages = [{"page_num": 1, "text": text, "bbox_data": []}]
    facts = await extract_facts(text, pages)
    return [f.normalized_value for f in facts if f.kind.value == "reference"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Notice reference: NMP-TEST-2048", "NMP-TEST-2048"),
        ("Notice reference: NB-TEST-20481", "NB-TEST-20481"),
        ("Claim reference: HGI-DEMO-7782", "HGI-DEMO-7782"),
        ("Reference: CB-TEST-99107", "CB-TEST-99107"),
        ("Policy reference: POLICY-TEST-82", "POLICY-TEST-82"),
        ("Policy reference: POLICY-TEST-44", "POLICY-TEST-44"),
        ("Reference: RO-TEST-3105", "RO-TEST-3105"),
        ("Ref: GST/2024/11/0042", "GST/2024/11/0042"),
        ("Reference No: IT/2024/10/0156", "IT/2024/10/0156"),
    ],
)
async def test_known_reference_formats(text, expected):
    assert expected in await _refs(text)


@pytest.mark.asyncio
async def test_no_junk_reference_from_glued_label():
    """'referencenumber90' must not become a reference value."""
    refs = await _refs("see referencenumber90 for details")
    assert refs == []


@pytest.mark.asyncio
async def test_no_bare_digit_reference():
    refs = await _refs("Reference number: 90")
    assert refs == []


@pytest.mark.asyncio
async def test_truncated_id_dropped():
    """'DPS-TEST-??' is incomplete; the fragment 'DPS-TEST' has no digit."""
    refs = await _refs("Ref: DPS-TEST-??\nDate: unclear")
    assert refs == []


@pytest.mark.asyncio
async def test_date_fragment_not_reference():
    refs = await _refs("Reference: 12/30 is wrong")
    assert "12/30" not in refs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
