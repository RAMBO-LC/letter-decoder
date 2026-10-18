"""Main pipeline orchestrator for Letter Decoder."""

from __future__ import annotations

import asyncio
import hashlib
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
    SourceInfo,
    Step,
    TrustAssessment,
    Verdict,
    VerificationStatus,
)

from .classifier import classify_letter
from .deterministic_extract import extract_facts
from .extract_text import extract_text
from .llm_constrained import explain_with_llm
from .pack_loader import load_notice_pack
from .preprocess import preprocess_image
from .trust import assess_trust, trust_warnings
from .verifier import verify_answer


def _to_warnings(pairs: list[tuple[str, str]]) -> list:
    from contract.models import Warning

    return [Warning(code=c, message=m) for c, m in pairs]


def _dedupe_warnings(warnings: list) -> list:
    seen: set[tuple[str, str]] = set()
    out = []
    for w in warnings:
        key = (w.code, w.message)
        if key not in seen:
            seen.add(key)
            out.append(w)
    return out

# Deadline roles in selection order: the most committal kind first.
_DEADLINE_ROLE_ORDER: list[tuple[str, DeadlineKind]] = [
    ("payment_deadline", DeadlineKind.PAYMENT),
    ("response_deadline", DeadlineKind.RESPONSE),
    ("appeal_deadline", DeadlineKind.APPEAL),
]


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
        queue_ms: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Process a letter and yield SSE events."""
        letter_id = uuid.uuid4().hex[:12]
        timings: dict[str, int] = {}
        if queue_ms:
            timings["queue"] = int(queue_ms)
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

            # Document identity: which file/content produced this answer.
            answer.source = self._build_source(file_path, text, extracted)

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
            t0 = time.perf_counter()
            notice_pack = await load_notice_pack(
                classification.notice_type_id, classification.country, self.notices_dir
            )
            timings["load_pack"] = int((time.perf_counter() - t0) * 1000)

            # Stage 6: Deadline by semantic role (never by whole-text heuristics)
            t0 = time.perf_counter()
            deadline = self._compute_deadline(facts, notice_pack)
            answer.deadline = deadline
            timings["deadline"] = int((time.perf_counter() - t0) * 1000)
            yield self._make_event("deadline", deadline.model_dump())

            # Stage 6b: Trust layer - claims vs verification
            trust = assess_trust(extracted.text, facts, classification, notice_pack)
            answer.trust = trust

            # Stage 7: Severity from pack (scam pressure overrides calm defaults)
            t0 = time.perf_counter()
            severity = self._compute_severity(facts, classification, notice_pack, trust)
            answer.severity = severity
            timings["severity"] = int((time.perf_counter() - t0) * 1000)
            yield self._make_event("severity", severity.model_dump())

            # Stage 8: Verdict (never imperative "pay" for unverified senders)
            t0 = time.perf_counter()
            verdict = self._compute_verdict(facts, classification, deadline, severity, trust)
            answer.verdict = verdict
            timings["verdict"] = int((time.perf_counter() - t0) * 1000)
            yield self._make_event("verdict", verdict.model_dump())

            # Stage 9: LLM explanation (or mock)
            yield self._make_event("stage", {"stage": "explain", "progress": 0.8})
            t0 = time.perf_counter()
            if self.engine_mode == "mock":
                explanation, steps, checklist, draft_replies, big_print = self._mock_explanation(
                    facts, classification, deadline, severity, notice_pack, trust
                )
            else:
                explanation, steps, checklist, draft_replies, big_print = await explain_with_llm(
                    facts,
                    classification,
                    deadline,
                    severity,
                    notice_pack,
                    language,
                    letter_text=extracted.text,
                    trust=trust,
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

            # Stage 10: Verification (evidence-based) + trust warnings
            yield self._make_event("stage", {"stage": "verify", "progress": 0.95})
            t0 = time.perf_counter()
            warnings = _dedupe_warnings(
                _to_warnings(trust_warnings(trust)) + await verify_answer(answer, facts)
            )
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

    def _build_source(self, file_path: Path | None, text: str | None, extracted) -> SourceInfo:
        """Document identity for the answer: what was actually analysed."""
        raw: bytes | None = None
        filename: str | None = None
        if file_path is not None and file_path.exists():
            raw = file_path.read_bytes()
            filename = file_path.name
        elif text is not None:
            raw = text.encode("utf-8", errors="replace")
        body = extracted.text or text or ""
        return SourceInfo(
            filename=filename,
            sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
            bytes=len(raw) if raw is not None else None,
            chars=len(body),
            preview=body[:300],
            method=extracted.method,
        )

    def _compute_deadline(self, facts: list[Fact], notice_pack: dict) -> Deadline:
        """Pick a deadline by the fact's semantic role, never by date alone.

        Conflicting dates in the same role yield the earliest with low
        confidence; the verifier surfaces the conflict as a warning.
        """
        for role, kind in _DEADLINE_ROLE_ORDER:
            candidates = [
                f
                for f in facts
                if f.role == role
                and f.verification == VerificationStatus.SUPPORTED
                and f.normalized_value
            ]
            if not candidates:
                continue
            if len(candidates) == 1:
                only = candidates[0]
                return Deadline(
                    fact_id=only.id,
                    kind=kind,
                    iso_date=only.normalized_value,
                    confidence=only.confidence,
                )
            earliest = min(candidates, key=lambda f: f.normalized_value or "")
            return Deadline(
                fact_id=earliest.id,
                kind=kind,
                iso_date=earliest.normalized_value,
                confidence=0.4,
            )
        return Deadline(fact_id=None, kind=DeadlineKind.UNKNOWN, iso_date=None, confidence=0.0)

    def _compute_severity(
        self,
        facts: list[Fact],
        classification: Classification,
        notice_pack: dict,
        trust: TrustAssessment | None = None,
    ) -> Severity:
        """Compute severity from classification, facts, and trust signals."""
        if trust is not None and trust.scam_pressure:
            return Severity(
                level=SeverityLevel.SEE_PROFESSIONAL,
                reason=(
                    "Verify first: the message uses high-pressure tactics and its "
                    "sender could not be verified."
                ),
                confidence=0.8,
            )
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
        trust: TrustAssessment | None = None,
    ) -> Verdict:
        """Generate a calm one-line verdict that never orders a payment."""
        sender = classification.sender if classification and classification.sender else None
        unverified = trust is not None and not trust.sender_verified
        if sender and unverified:
            who = f"A letter claiming to be from {sender}"
        elif sender:
            who = sender
        else:
            who = "This letter"

        if trust is not None and trust.scam_pressure:
            return Verdict(
                text=(
                    f"{who} demands money under pressure; its authenticity is "
                    "unconfirmed. Do not pay before verifying through a channel "
                    "you obtain yourself."
                ),
                confidence=0.75,
            )

        amount_fact = next((f for f in facts if f.kind == FactKind.AMOUNT), None)
        amount_str = f" {amount_fact.normalized_value}" if amount_fact else ""

        if amount_fact and deadline.iso_date:
            base = f"{who} demands{amount_str} by {deadline.iso_date}."
        elif amount_fact:
            base = f"{who} claims{amount_str} is owed but states no deadline."
        elif deadline.iso_date:
            base = f"{who} asks for a response by {deadline.iso_date}."
        else:
            return Verdict(
                text="No payment or response deadline was found in this letter.",
                confidence=0.7,
            )

        if unverified:
            tail = " The sender is unverified - confirm it independently before acting."
        else:
            tail = " Verify through official channels before paying."
        return Verdict(text=base + tail, confidence=0.85)

    def _mock_explanation(
        self,
        facts: list[Fact],
        classification: Classification,
        deadline: Deadline,
        severity: Severity,
        notice_pack: dict,
        trust: TrustAssessment | None = None,
    ) -> tuple[Explanation, list[Step], list[ChecklistItem], Any, Any]:
        """Generate mock explanation for testing."""
        from contract.models import BigPrint, DraftReplies

        simple = notice_pack.get("mock_simple", "This is a mock explanation.")
        detailed = notice_pack.get("mock_detailed", "Detailed mock explanation for testing.")

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
                Step(
                    text="Check the letter for any stated deadline - none was found",
                    fact_ids=[],
                )
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
            neutral="I acknowledge receipt of your letter. I am reviewing its "
            "contents and will respond. This note is an editable example."
        )

        big_print_lines = [
            notice_pack.get("mock_big_print_1", "Line 1"),
            notice_pack.get("mock_big_print_2", "Line 2"),
        ]
        if trust is not None and trust.verify_before_payment:
            big_print_lines = ["VERIFY BEFORE PAYING"] + big_print_lines
        big_print = BigPrint(lines=big_print_lines[:3])

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
