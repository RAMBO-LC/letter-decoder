"""Main pipeline orchestrator for Letter Decoder."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any

from contract.models import (
    Answer,
    AnswerStatus,
    ChecklistItem,
    Classification,
    Deadline,
    DeadlineKind,
    Explanation,
    Fact,
    FactKind,
    Meta,
    Severity,
    SeverityLevel,
    Step,
    Verdict,
)

from .classifier import classify_letter
from .deterministic_extract import extract_facts
from .extract_text import extract_text
from .llm_constrained import explain_with_llm
from .pack_loader import load_notice_pack
from .preprocess import preprocess_image
from .verifier import verify_answer


class LetterDecoderPipeline:
    """Main pipeline for processing letters."""

    def __init__(
        self,
        engine_mode: str = "real",
        ollama_host: str = "http://127.0.0.1:11434",
        model_name: str = "qwen2.5:7b",
        notices_dir: Path = Path("notices"),
        templates_dir: Path = Path("templates"),
    ):
        self.engine_mode = engine_mode
        self.ollama_host = ollama_host
        self.model_name = model_name
        self.notices_dir = notices_dir
        self.templates_dir = templates_dir
        self._mock_examples: dict[str, Answer] = {}

    async def process(
        self,
        file_path: Path | None = None,
        text: str | None = None,
        country: str = "XX",
        language: str = "en",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Process a letter and yield SSE events."""
        letter_id = uuid.uuid4().hex[:12]
        timings: dict[str, int] = {}
        start_total = time.perf_counter()

        # Initialize answer
        answer = Answer(
            id=letter_id,
            status=AnswerStatus.READING,
            meta=Meta(
                engine_version="0.1.0",
                model=self.model_name if self.engine_mode == "real" else "mock",
                offline=True,
                timings_ms={},
            ),
        )

        try:
            # Stage 1: Preprocess
            yield self._make_event("stage", {"stage": "preprocess", "progress": 0.1})
            t0 = time.perf_counter()
            image_data = await preprocess_image(file_path) if file_path else None
            timings["preprocess"] = int((time.perf_counter() - t0) * 1000)

            # Stage 2: Extract text
            yield self._make_event("stage", {"stage": "extract_text", "progress": 0.25})
            t0 = time.perf_counter()
            extracted = await extract_text(image_data, file_path, text)
            timings["extract_text"] = int((time.perf_counter() - t0) * 1000)

            # Stage 3: Deterministic fact extraction
            yield self._make_event("stage", {"stage": "extract_facts", "progress": 0.4})
            t0 = time.perf_counter()
            facts = await extract_facts(extracted.text, extracted.pages)
            answer.facts = facts
            timings["extract_facts"] = int((time.perf_counter() - t0) * 1000)

            # Emit facts FIRST (deterministic, with bboxes)
            yield self._make_event("facts", {"facts": [f.model_dump() for f in facts]})

            # Stage 4: Classification
            yield self._make_event("stage", {"stage": "classify", "progress": 0.55})
            t0 = time.perf_counter()
            classification = await classify_letter(
                extracted.text, facts, country, language, self.notices_dir
            )
            answer.classification = classification
            timings["classify"] = int((time.perf_counter() - t0) * 1000)
            yield self._make_event("classification", classification.model_dump())

            # Stage 5: Load notice pack
            yield self._make_event("stage", {"stage": "load_pack", "progress": 0.65})
            notice_pack = await load_notice_pack(
                classification.notice_type_id, classification.country, self.notices_dir
            )

            # Stage 6: Deadline from pack logic
            deadline = self._compute_deadline(facts, notice_pack)
            answer.deadline = deadline
            yield self._make_event("deadline", deadline.model_dump())

            # Stage 7: Severity from pack
            severity = self._compute_severity(facts, classification, notice_pack)
            answer.severity = severity
            yield self._make_event("severity", severity.model_dump())

            # Stage 8: Verdict
            verdict = self._compute_verdict(facts, classification, deadline, severity)
            answer.verdict = verdict
            yield self._make_event("verdict", verdict.model_dump())

            # Stage 9: LLM explanation (or mock)
            yield self._make_event("stage", {"stage": "explain", "progress": 0.8})
            t0 = time.perf_counter()
            if self.engine_mode == "mock":
                explanation, steps, checklist, draft_replies, big_print = self._mock_explanation(
                    facts, classification, deadline, severity, notice_pack
                )
            else:
                explanation, steps, checklist, draft_replies, big_print = await explain_with_llm(
                    facts, classification, deadline, severity, notice_pack, language
                )
            answer.explanation = explanation
            answer.steps = steps
            answer.checklist = checklist
            answer.draft_replies = draft_replies
            answer.big_print = big_print
            timings["explain"] = int((time.perf_counter() - t0) * 1000)

            yield self._make_event("explanation", explanation.model_dump())
            yield self._make_event("steps", {"steps": [s.model_dump() for s in steps]})
            yield self._make_event("checklist", {"checklist": [c.model_dump() for c in checklist]})
            yield self._make_event("big_print", big_print.model_dump())

            # Stage 10: Verification
            yield self._make_event("stage", {"stage": "verify", "progress": 0.95})
            t0 = time.perf_counter()
            warnings = await verify_answer(answer, facts)
            answer.warnings = warnings
            for warning in warnings:
                yield self._make_event("warning", warning.model_dump())
            timings["verify"] = int((time.perf_counter() - t0) * 1000)

            # Finalize
            answer.status = AnswerStatus.READY
            answer.updated_at = datetime.utcnow()
            answer.meta.timings_ms = timings
            answer.meta.timings_ms["total"] = int((time.perf_counter() - start_total) * 1000)

            yield self._make_event("done", answer.model_dump())

        except Exception as e:
            answer.status = AnswerStatus.ERROR
            yield self._make_event(
                "error", {"code": "internal", "message": str(e), "retryable": True}
            )

    def _make_event(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"id": uuid.uuid4().hex[:8], "event": event, "data": data}

    def _compute_deadline(self, facts: list[Fact], notice_pack: dict) -> Deadline:
        """Compute deadline from facts and notice pack rules."""
        deadline_facts = [f for f in facts if f.kind == FactKind.DATE]
        if not deadline_facts:
            return Deadline(fact_id=None, kind=DeadlineKind.UNKNOWN, iso_date=None, confidence=0.0)

        # Simple heuristic: latest date is likely the deadline
        best_fact = max(deadline_facts, key=lambda f: f.confidence)
        return Deadline(
            fact_id=best_fact.id,
            kind=DeadlineKind.PAYMENT,
            iso_date=best_fact.normalized_value,
            confidence=best_fact.confidence * 0.9,
        )

    def _compute_severity(
        self, facts: list[Fact], classification: Classification, notice_pack: dict
    ) -> Severity:
        """Compute severity from classification and facts."""
        pack_severity = notice_pack.get("severity", "routine")
        return Severity(
            level=SeverityLevel(pack_severity),
            reason=notice_pack.get("severity_reason", ""),
            confidence=classification.confidence * 0.9,
        )

    def _compute_verdict(
        self,
        facts: list[Fact],
        classification: Classification,
        deadline: Deadline,
        severity: Severity,
    ) -> Verdict:
        """Generate one-line verdict."""
        sender = classification.sender or "Unknown sender"
        amount_fact = next((f for f in facts if f.kind == FactKind.AMOUNT), None)
        amount_str = f" {amount_fact.normalized_value}" if amount_fact else ""
        deadline_str = f" by {deadline.iso_date}" if deadline.iso_date else ""
        return Verdict(
            text=f"{sender} says you owe{amount_str}. Pay{deadline_str}.",
            confidence=0.85,
        )

    def _mock_explanation(
        self,
        facts: list[Fact],
        classification: Classification,
        deadline: Deadline,
        severity: Severity,
        notice_pack: dict,
    ) -> tuple[Explanation, list[Step], list[ChecklistItem], any, any]:
        """Generate mock explanation for testing."""
        from contract.models import BigPrint, DraftReplies

        simple = notice_pack.get("mock_simple", "This is a mock explanation.")
        detailed = notice_pack.get("mock_detailed", "Detailed mock explanation for testing.")

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

        return (
            Explanation(simple=simple, detailed=detailed),
            steps,
            checklist,
            draft_replies,
            big_print,
        )

    def load_mock_example(self, example_name: str) -> Answer:
        """Load a mock example by name."""
        import json

        example_path = Path("contract/examples") / f"{example_name}.json"
        if example_path.exists():
            with open(example_path) as f:
                data = json.load(f)
                return Answer(**data)
        raise ValueError(f"Mock example not found: {example_name}")

    async def process_mock(self, example_name: str) -> AsyncGenerator[dict[str, Any], None]:
        """Process a mock example with simulated delays."""
        answer = self.load_mock_example(example_name)

        # Simulate the event sequence with delays
        stages = [
            ("stage", {"stage": "preprocess", "progress": 0.1}, 100),
            ("stage", {"stage": "extract_text", "progress": 0.25}, 300),
            ("stage", {"stage": "extract_facts", "progress": 0.4}, 100),
            ("facts", {"facts": [f.model_dump() for f in answer.facts]}, 50),
            ("stage", {"stage": "classify", "progress": 0.55}, 100),
            (
                "classification",
                answer.classification.model_dump() if answer.classification else {},
                50,
            ),
            ("stage", {"stage": "load_pack", "progress": 0.65}, 50),
            ("deadline", answer.deadline.model_dump() if answer.deadline else {}, 50),
            ("severity", answer.severity.model_dump() if answer.severity else {}, 50),
            ("verdict", answer.verdict.model_dump() if answer.verdict else {}, 50),
            ("stage", {"stage": "explain", "progress": 0.8}, 200),
            ("explanation", answer.explanation.model_dump() if answer.explanation else {}, 50),
            ("steps", {"steps": [s.model_dump() for s in answer.steps]}, 50),
            ("checklist", {"checklist": [c.model_dump() for c in answer.checklist]}, 50),
            ("big_print", answer.big_print.model_dump() if answer.big_print else {}, 50),
            ("stage", {"stage": "verify", "progress": 0.95}, 50),
        ]

        for event_type, data, delay in stages:
            if data:
                yield self._make_event(event_type, data)
            await asyncio.sleep(delay / 1000)

        for warning in answer.warnings:
            yield self._make_event("warning", warning.model_dump())
            await asyncio.sleep(0.01)

        answer.status = AnswerStatus.READY
        yield self._make_event("done", answer.model_dump())
