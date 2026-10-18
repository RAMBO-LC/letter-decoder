"""LLM explanation with JSON-constrained output."""

from __future__ import annotations

import json

from contract.models import (
    BigPrint,
    ChecklistItem,
    Classification,
    Deadline,
    DraftReplies,
    Explanation,
    Fact,
    Severity,
    Step,
    TrustAssessment,
)

SYSTEM_PROMPT_TEMPLATE = """You explain official letters to a worried non-expert in {language}.

SOURCE RULES (strict):
- Use ONLY the LETTER TEXT below and the FACTS list. The facts were machine-extracted from that same text.
- Quote or paraphrase only wording that appears in the LETTER TEXT. Never invent dates, amounts, reference numbers, authorities, statutes, penalties, phone numbers, or websites.
- Never compute or replace a stated deadline (no "+14 days" arithmetic). If the letter uses relative wording like "within 14 days", quote that wording and say the letter does not give an absolute date for it.
- If facts conflict, say so plainly and advise verifying with the sender; do not pick one as the truth.
- Dates: state each date with its role as given (issue date, payment deadline, appeal deadline, etc.). If no deadline exists, say none was found.

TRUST RULES:
- The sender's identity is {sender_trust}. Refer to the sender as a claim unless it is verified.
- {payment_advice}
- Mark any draft reply wording as an editable example; drafts must not admit liability or promise payment.

Tone: calm, plain language. Never alarming, never shaming.

Output JSON matching this exact schema:
{{
  "simple": "string - plain language summary in 1-2 sentences, source-backed",
  "detailed": "string - detailed explanation in 3-5 sentences using only letter wording and facts",
  "steps": [{{"text": "string", "detail": "string or null", "fact_ids": ["string"]}}],
  "checklist": [{{"text": "string"}}],
  "draft_reply_neutral": "string - acknowledgement that admits nothing, editable example wording",
  "big_print_lines": ["string", "string", "string"]
}}

FACTS:
{facts_json}

CLASSIFICATION:
{classification_json}

DEADLINE:
{deadline_json}

SEVERITY:
{severity_json}

NOTICE PACK:
{pack_json}

LETTER TEXT:
{letter_text}
"""


async def explain_with_llm(
    facts: list[Fact],
    classification: Classification,
    deadline: Deadline,
    severity: Severity,
    notice_pack: dict,
    language: str,
    letter_text: str = "",
    trust: TrustAssessment | None = None,
) -> tuple[Explanation, list[Step], list[ChecklistItem], DraftReplies, BigPrint]:
    """Generate explanation using local LLM with JSON-constrained output."""
    facts_json = [
        {
            "kind": f.kind.value,
            "label": f.label,
            "raw": f.raw_value,
            "normalized": f.normalized_value,
            "role": f.role,
            "verification": f.verification.value,
            "confidence": f.confidence,
            "source_quote": f.source.text,
        }
        for f in facts
    ]

    sender_trust = "UNVERIFIED - treat as a claim"
    payment_advice = "Advise verifying the sender independently before any payment."
    if trust is not None:
        if trust.sender_verified:
            sender_trust = "verified against the notice pack"
        if trust.verify_before_payment:
            payment_advice = (
                "Explicitly advise the reader to verify this letter through an "
                "independently obtained official channel before paying, replying "
                "with details, or sharing documents. Never say 'pay by' or tell "
                "them to send money."
            )
        elif trust.payment_instructions_present is False:
            payment_advice = "Note that the letter states no payment destination."

    truncated_text = letter_text[:6000] if letter_text else "[not provided]"

    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        language=language,
        facts_json=json.dumps(facts_json, ensure_ascii=False, indent=2),
        classification_json=classification.model_dump_json() if classification else "{}",
        deadline_json=deadline.model_dump_json() if deadline else "{}",
        severity_json=severity.model_dump_json() if severity else "{}",
        pack_json=json.dumps(notice_pack, ensure_ascii=False, indent=2),
        sender_trust=sender_trust,
        payment_advice=payment_advice,
        letter_text=truncated_text,
    )

    try:
        import ollama

        client = ollama.AsyncClient(host="http://127.0.0.1:11434")

        response = await client.chat(
            model="qwen2.5:7b",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the explanation JSON."},
            ],
            format="json",
            options={"temperature": 0.1, "num_ctx": 8192, "num_predict": 700},
        )

        result = json.loads(response["message"]["content"])
    except Exception:
        return _fallback_explanation(
            facts, classification, deadline, severity, notice_pack, trust
        )

    return _parse_llm_result(result, facts, deadline, trust)


def _fallback_explanation(
    facts: list[Fact],
    classification: Classification,
    deadline: Deadline,
    severity: Severity,
    notice_pack: dict,
    trust: TrustAssessment | None = None,
) -> tuple[Explanation, list[Step], list[ChecklistItem], DraftReplies, BigPrint]:
    """Fallback explanation when LLM unavailable."""
    simple = notice_pack.get("mock_simple", "This is a fallback explanation.")
    detailed = notice_pack.get("mock_detailed", "Detailed fallback explanation.")

    steps = [Step(text="Review the letter details", fact_ids=[f.id for f in facts[:2]])]
    if deadline.iso_date:
        steps.append(
            Step(
                text=f"Decide how to respond by the stated date ({deadline.iso_date})",
                fact_ids=[deadline.fact_id] if deadline.fact_id else [],
            )
        )
    else:
        steps.append(
            Step(text="Check the letter for any stated deadline - none was found", fact_ids=[])
        )
    if trust is not None and trust.verify_before_payment:
        steps.append(
            Step(
                text="Verify the sender through an independently obtained official "
                "channel before paying or sharing details",
                fact_ids=[],
            )
        )
    else:
        steps.append(Step(text="Keep a copy for your records", fact_ids=[]))

    checklist = [
        ChecklistItem(text="Original letter"),
        ChecklistItem(text="Supporting documents"),
    ]

    draft_replies = DraftReplies(
        neutral="I acknowledge receipt of your letter. I am reviewing its contents "
        "and will respond. This is editable example wording."
    )

    big_print_lines = [
        notice_pack.get("mock_big_print_1", "Line 1"),
        notice_pack.get("mock_big_print_2", "Line 2"),
    ]
    if trust is not None and trust.verify_before_payment:
        big_print_lines = ["VERIFY BEFORE PAYING"] + big_print_lines
    big_print = BigPrint(lines=big_print_lines[:3])

    return Explanation(simple=simple, detailed=detailed), steps, checklist, draft_replies, big_print


def _parse_llm_result(
    result: dict,
    facts: list[Fact],
    deadline: Deadline,
    trust: TrustAssessment | None = None,
) -> tuple[Explanation, list[Step], list[ChecklistItem], DraftReplies, BigPrint]:
    """Parse and validate LLM result."""
    simple = result.get("simple", "Explanation unavailable.")
    detailed = result.get("detailed", simple)

    steps = []
    for i, step_data in enumerate(result.get("steps", [])[:3]):
        steps.append(
            Step(
                text=step_data.get("text", f"Step {i + 1}"),
                detail=step_data.get("detail"),
                fact_ids=step_data.get("fact_ids", []),
            )
        )

    checklist = []
    for item_data in result.get("checklist", []):
        if item_data.get("text"):
            checklist.append(ChecklistItem(text=item_data["text"]))

    draft_replies = DraftReplies(
        neutral=result.get(
            "draft_reply_neutral",
            "I acknowledge receipt of your letter and am reviewing it. "
            "This is editable example wording.",
        ),
    )

    big_print_lines = result.get("big_print_lines", [])
    if not big_print_lines and deadline.iso_date:
        big_print_lines = [f"Due: {deadline.iso_date}"]
    if (
        trust is not None
        and trust.verify_before_payment
        and not any("verify" in line.lower() for line in big_print_lines)
    ):
        big_print_lines = ["VERIFY BEFORE PAYING", *big_print_lines]
    big_print = BigPrint(lines=big_print_lines[:3])

    return Explanation(simple=simple, detailed=detailed), steps, checklist, draft_replies, big_print
