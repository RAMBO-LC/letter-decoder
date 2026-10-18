"""Document identity and pipeline integration (mock mode, offline)."""

import pytest

from engine.pipeline import LetterDecoderPipeline

SPEC_LETTER = """MUNICIPAL NOTICE
Notice reference: NMP-TEST-2048
This notice was issued on 6 October 2026.
The incident occurred on 4 October 2026.
Payment deadline: 20 October 2026.
A penalty of I1,200 is payable.
"""


async def _run(text: str, queue_ms: int = 0) -> dict:
    p = LetterDecoderPipeline(engine_mode="mock")
    events = []
    async for event in p.process(text=text, country="XX", language="en", queue_ms=queue_ms):
        events.append(event)
    done = next(e for e in events if e["event"] == "done")
    return {"events": events, "done": done["data"]}


@pytest.mark.asyncio
async def test_answer_carries_source_identity():
    result = await _run(SPEC_LETTER)
    source = result["done"]["source"]
    assert source is not None
    assert source["filename"] is None  # text input, not a file
    assert source["chars"] == len(SPEC_LETTER)
    assert source["preview"] == SPEC_LETTER[:300]
    assert source["sha256"]
    assert source["method"] == "text_input"


@pytest.mark.asyncio
async def test_answer_carries_trust():
    result = await _run(SPEC_LETTER)
    trust = result["done"]["trust"]
    assert trust is not None
    assert trust["sender_verified"] is False
    assert trust["verify_before_payment"] is True
    codes = {w["code"] for w in result["done"]["warnings"]}
    assert "sender_identity_unverified" in codes
    assert "verify_before_payment" in codes


@pytest.mark.asyncio
async def test_deadline_from_payment_role_not_issue_date():
    result = await _run(SPEC_LETTER)
    deadline = result["done"]["deadline"]
    assert deadline["kind"] == "payment"
    assert deadline["iso_date"] == "2026-10-20"


@pytest.mark.asyncio
async def test_verdict_not_imperative_payment():
    result = await _run(SPEC_LETTER)
    text = result["done"]["verdict"]["text"].lower()
    assert "pay by" not in text
    assert "unverified" in text


@pytest.mark.asyncio
async def test_timings_cover_all_stages():
    result = await _run(SPEC_LETTER, queue_ms=123)
    timings = result["done"]["meta"]["timings_ms"]
    for stage in (
        "queue",
        "preprocess",
        "extract_text",
        "extract_facts",
        "classify",
        "load_pack",
        "deadline",
        "severity",
        "verdict",
        "explain",
        "verify",
        "total",
    ):
        assert stage in timings, f"missing timing: {stage}"


@pytest.mark.asyncio
async def test_mock_draft_admits_nothing():
    result = await _run(SPEC_LETTER)
    draft = result["done"]["draft_replies"]["neutral"].lower()
    assert "pay" not in draft
    assert "liable" not in draft
    assert "editable" in draft or "example" in draft


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
