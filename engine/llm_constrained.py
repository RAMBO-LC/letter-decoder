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
)

SYSTEM_PROMPT_TEMPLATE = """You explain official letters to a worried non-expert in {language}.
Use ONLY the facts provided in FACTS and the letter text.
Never invent dates, amounts, or legal claims.
If unsure, say 'check with a professional'.
Output JSON matching this exact schema:
{{
  "simple": "string - plain language summary in 1-2 sentences",
  "detailed": "string - detailed explanation in 3-5 sentences",
  "steps": [{{"text": "string", "detail": "string or null", "fact_ids": ["string"]}}],
  "checklist": [{{"text": "string"}}],
  "draft_reply_neutral": "string",
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
) -> tuple[Explanation, list[Step], list[ChecklistItem], DraftReplies, BigPrint]:
    """Generate explanation using local LLM with JSON-constrained output."""
    # Prepare facts JSON
    facts_json = [
        {
            "kind": f.kind.value,
            "label": f.label,
            "raw": f.raw_value,
            "normalized": f.normalized_value,
            "confidence": f.confidence,
        }
        for f in facts
    ]

    # Build prompt
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        language=language,
        facts_json=json.dumps(facts_json, ensure_ascii=False, indent=2),
        classification_json=classification.model_dump_json() if classification else "{}",
        deadline_json=deadline.model_dump_json() if deadline else "{}",
        severity_json=severity.model_dump_json() if severity else "{}",
        pack_json=json.dumps(notice_pack, ensure_ascii=False, indent=2),
        letter_text="[Letter text would be here in real implementation]",
    )

    # Try to call Ollama
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
            options={"temperature": 0.1},
        )

        result = json.loads(response["message"]["content"])
    except Exception:
        # Fallback to mock
        return _fallback_explanation(facts, classification, deadline, severity, notice_pack)

    # Parse and validate result
    return _parse_llm_result(result, facts, deadline)


def _fallback_explanation(
    facts: list[Fact],
    classification: Classification,
    deadline: Deadline,
    severity: Severity,
    notice_pack: dict,
) -> tuple[Explanation, list[Step], list[ChecklistItem], DraftReplies, BigPrint]:
    """Fallback explanation when LLM unavailable."""
    simple = notice_pack.get("mock_simple", "This is a fallback explanation.")
    detailed = notice_pack.get("mock_detailed", "Detailed fallback explanation.")

    steps = [
        Step(text="Review the letter details", fact_ids=[f.id for f in facts[:2]]),
        Step(
            text="Take action by the deadline",
            fact_ids=[deadline.fact_id] if deadline.fact_id else [],
        ),
        Step(text="Keep a copy for your records", fact_ids=[]),
    ]

    checklist = [
        ChecklistItem(text="Original letter"),
        ChecklistItem(text="Supporting documents"),
    ]

    draft_replies = DraftReplies(
        neutral="Thank you for the notice. I will review and respond appropriately."
    )

    big_print = BigPrint(
        lines=[
            notice_pack.get("mock_big_print_1", "Line 1"),
            notice_pack.get("mock_big_print_2", "Line 2"),
        ]
    )

    return Explanation(simple=simple, detailed=detailed), steps, checklist, draft_replies, big_print


def _parse_llm_result(
    result: dict,
    facts: list[Fact],
    deadline: Deadline,
) -> tuple[Explanation, list[Step], list[ChecklistItem], DraftReplies, BigPrint]:
    """Parse and validate LLM result."""
    # Extract fields with defaults
    simple = result.get("simple", "Explanation unavailable.")
    detailed = result.get("detailed", simple)

    # Parse steps
    steps = []
    for i, step_data in enumerate(result.get("steps", [])[:3]):
        steps.append(
            Step(
                text=step_data.get("text", f"Step {i + 1}"),
                detail=step_data.get("detail"),
                fact_ids=step_data.get("fact_ids", []),
            )
        )

    # Parse checklist
    checklist = []
    for item_data in result.get("checklist", []):
        checklist.append(ChecklistItem(text=item_data.get("text", "")))

    # Draft replies
    draft_replies = DraftReplies(
        neutral=result.get(
            "draft_reply_neutral", "Thank you for the notice. I will review and respond."
        ),
    )

    # Big print
    big_print_lines = result.get("big_print_lines", [])
    if not big_print_lines and deadline.iso_date:
        big_print_lines = [f"Due: {deadline.iso_date}"]
    big_print = BigPrint(lines=big_print_lines[:3])

    return Explanation(simple=simple, detailed=detailed), steps, checklist, draft_replies, big_print
