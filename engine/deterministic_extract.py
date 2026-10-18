"""Deterministic extraction of dates, amounts, references from text."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import dateparser

from contract.models import BoundingBox, Fact, FactKind, SourceSpan

# Date patterns
DATE_PATTERNS = [
    r"\b(\d{1,2})[\s/-](\d{1,2})[\s/-](\d{2,4})\b",  # DD/MM/YYYY or DD-MM-YYYY
    r"\b(\d{4})[\s/-](\d{1,2})[\s/-](\d{1,2})\b",  # YYYY/MM/DD
    r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{2,4})\b",  # DD Mon YYYY
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{2,4})\b",  # Mon DD, YYYY
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{2,4})\b",
    r"\bby\s+(\d{1,2}[\s/-]\d{1,2}[\s/-]\d{2,4})\b",
    r"\b(on|before|by)\s+(\d{1,2}\s+\w+\s+\d{2,4})\b",
]

# Amount patterns (Indian currency focus)
AMOUNT_PATTERNS = [
    r"(?:Rs\.?|INR|₹)\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
    r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:Rs\.?|INR|₹)",
    r"(?:amount|total|due|pay|penalty|fine|tax)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)",
]

# Reference patterns
REF_PATTERNS = [
    r"(?:Ref|Reference|Ref\.|No\.|Number)\s*[:\-]?\s*([A-Z0-9/\\-]{6,})",
    r"\b([A-Z]{2,4}/\d{4}/\d{2}/\d{4,6})\b",  # IN format like GST/2024/11/0042
    r"\b([A-Z]{2,4}/\d{4}/\d{4,6})\b",
]


async def extract_facts(text: str, pages: list[dict]) -> list[Fact]:
    """Extract all deterministic facts from text."""
    facts = []

    # Extract dates
    date_facts = _extract_dates(text, pages)
    facts.extend(date_facts)

    # Extract amounts
    amount_facts = _extract_amounts(text, pages)
    facts.extend(amount_facts)

    # Extract references
    ref_facts = _extract_references(text, pages)
    facts.extend(ref_facts)

    # Extract sender (simple heuristic)
    sender_facts = _extract_sender(text, pages)
    facts.extend(sender_facts)

    return facts


def _extract_dates(text: str, pages: list[dict]) -> list[Fact]:
    """Extract dates with source spans."""
    facts = []
    seen_normalized = set()

    # Use regex patterns first (more reliable)
    for pattern in DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matched = match.group(0)
            # Try to parse with dateparser
            parsed_date = dateparser.parse(
                matched,
                settings={
                    "PREFER_DAY_OF_MONTH": "first",
                    "PREFER_DATES_FROM": "future",
                    "RELATIVE_BASE": datetime.now(),
                },
            )
            if parsed_date:
                iso_date = parsed_date.strftime("%Y-%m-%d")
                if iso_date in seen_normalized:
                    continue
                seen_normalized.add(iso_date)

                source = _find_source_span(matched, pages)
                fact = Fact(
                    kind=FactKind.DATE,
                    label=_infer_date_label(matched, text),
                    raw_value=matched,
                    normalized_value=iso_date,
                    confidence=0.85 if source else 0.6,
                    verified=bool(source),
                    source=source or SourceSpan(page=1, text=matched, bbox=None),
                )
                facts.append(fact)

    # Also try dateparser.parse on the whole text for any missed dates
    parsed = dateparser.parse(
        text,
        settings={
            "PREFER_DAY_OF_MONTH": "first",
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.now(),
        },
    )
    if parsed:
        iso_date = parsed.strftime("%Y-%m-%d")
        if iso_date not in seen_normalized:
            # Try to find the matched portion in text
            source = _find_source_span(parsed.isoformat()[:10], pages) or _find_source_span(
                str(parsed), pages
            )
            fact = Fact(
                kind=FactKind.DATE,
                label=_infer_date_label(str(parsed), text),
                raw_value=str(parsed),
                normalized_value=iso_date,
                confidence=0.6,
                verified=bool(source),
                source=source or SourceSpan(page=1, text=str(parsed), bbox=None),
            )
            facts.append(fact)

    return facts


def _extract_amounts(text: str, pages: list[dict]) -> list[Fact]:
    """Extract monetary amounts."""
    facts = []
    seen_normalized = set()

    for pattern in AMOUNT_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matched = match.group(0)
            amount_str = match.group(1) if match.lastindex else matched

            # Clean amount string
            clean_amount = (
                amount_str.replace(",", "")
                .replace("₹", "")
                .replace("Rs", "")
                .replace(".", "")
                .strip()
            )
            try:
                amount_val = Decimal(clean_amount)
            except (InvalidOperation, ValueError):
                continue

            normalized = f"{amount_val:.2f} INR"
            if normalized in seen_normalized:
                continue
            seen_normalized.add(normalized)

            source = _find_source_span(matched, pages)
            fact = Fact(
                kind=FactKind.AMOUNT,
                label=_infer_amount_label(matched, text),
                raw_value=matched,
                normalized_value=normalized,
                confidence=0.85 if source else 0.6,
                verified=bool(source),
                source=source or SourceSpan(page=1, text=matched, bbox=None),
            )
            facts.append(fact)

    return facts


def _extract_references(text: str, pages: list[dict]) -> list[Fact]:
    """Extract reference numbers."""
    facts = []
    seen_normalized = set()

    for pattern in REF_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matched = match.group(0)
            ref_value = match.group(1) if match.lastindex else matched

            if ref_value in seen_normalized:
                continue
            seen_normalized.add(ref_value)

            source = _find_source_span(matched, pages)
            fact = Fact(
                kind=FactKind.REFERENCE,
                label="Reference number",
                raw_value=matched,
                normalized_value=ref_value,
                confidence=0.9 if source else 0.7,
                verified=bool(source),
                source=source or SourceSpan(page=1, text=matched, bbox=None),
            )
            facts.append(fact)

    return facts


def _extract_sender(text: str, pages: list[dict]) -> list[Fact]:
    """Extract sender/organization name (heuristic)."""
    facts = []

    lines = text.split("\n")[:10]
    sender_keywords = [
        "department",
        "ministry",
        "corporation",
        "bank",
        "insurance",
        "tax",
        "revenue",
        "municipal",
        "court",
        "tribunal",
        "authority",
    ]

    for line in lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in sender_keywords):
            source = _find_source_span(line.strip(), pages)
            fact = Fact(
                kind=FactKind.SENDER,
                label="Sender",
                raw_value=line.strip(),
                normalized_value=line.strip(),
                confidence=0.7 if source else 0.5,
                verified=bool(source),
                source=source or SourceSpan(page=1, text=line.strip(), bbox=None),
            )
            facts.append(fact)
            break

    return facts


def _find_source_span(matched_text: str, pages: list[dict]) -> SourceSpan | None:
    """Find the source span (page, text, bbox) for matched text."""
    for page in pages:
        page_text = page.get("text", "")
        if matched_text in page_text:
            bbox_data = page.get("bbox_data", [])
            best_bbox = None
            for item in bbox_data:
                item_text = item.get("text", "")
                if (
                    matched_text.lower() in item_text.lower()
                    or item_text.lower() in matched_text.lower()
                ):
                    b = item.get("bbox")
                    if b:
                        best_bbox = BoundingBox(**b)
                        break

            return SourceSpan(
                page=page.get("page_num", 1),
                text=matched_text,
                bbox=best_bbox,
            )

    return None


def _infer_date_label(matched: str, context: str) -> str:
    """Infer label for date from context."""
    context_lower = context.lower()

    if any(kw in context_lower for kw in ["due", "pay by", "payment by", "deadline"]):
        return "Due date"
    elif any(kw in context_lower for kw in ["respond", "reply", "response", "answer"]):
        return "Response deadline"
    elif any(kw in context_lower for kw in ["appeal", "appeal by"]):
        return "Appeal deadline"
    elif any(kw in context_lower for kw in ["hearing", "court date"]):
        return "Hearing date"
    elif any(kw in context_lower for kw in ["issue", "issued", "date"]):
        return "Issue date"
    return "Date"


def _infer_amount_label(matched: str, context: str) -> str:
    """Infer label for amount from context."""
    context_lower = context.lower()

    if any(kw in context_lower for kw in ["penalty", "fine"]):
        return "Penalty amount"
    elif any(kw in context_lower for kw in ["tax", "gst"]):
        return "Tax amount"
    elif any(kw in context_lower for kw in ["claim", "approved", "payable"]):
        return "Claim amount"
    elif any(kw in context_lower for kw in ["due", "payable", "amount due"]):
        return "Amount due"
    elif any(kw in context_lower for kw in ["refund", "credit"]):
        return "Refund amount"
    return "Amount"
