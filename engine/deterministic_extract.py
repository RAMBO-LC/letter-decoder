"""Deterministic extraction of dates, amounts, references from text.

Design rules:
- Facts are classified from the sentence they appear in, never from the whole
  document, so a date's role (issue vs payment deadline) cannot leak across
  unrelated sentences.
- A fact is only emitted when its raw value can be found in the source text;
  anything else is dropped rather than shown as verified.
- No whole-text date fallback: unmatched fragments (e.g. "1?/10/2026") yield
  no date instead of a fabricated one.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import dateparser

from contract.models import (
    BoundingBox,
    Fact,
    FactKind,
    SourceSpan,
    VerificationStatus,
)

# --- Date patterns (ordered; dedupe by (iso, role) resolves overlaps) ---
DATE_PATTERNS = [
    r"\b(\d{1,2})[\s/-](\d{1,2})[\s/-](\d{2,4})\b",  # DD/MM/YYYY or DD-MM-YYYY
    r"\b(\d{4})[\s/-](\d{1,2})[\s/-](\d{1,2})\b",  # YYYY/MM/DD
    r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{2,4})\b",  # DD Mon YYYY
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{2,4})\b",  # Mon DD, YYYY
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{2,4})\b",
    r"\b(?:by|on|before|to)\s+(\d{1,2}\s+\w+\s+\d{2,4})\b",
]

# Amount patterns. Currency must be adjacent, or the label + a
# thousands-separated/decimal figure must be present; bare digits are rejected
# so fragments like "90" or "12" are never treated as money.
AMOUNT_PATTERNS = [
    r"(?:Rs\.?|INR|₹)\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)",
    r"(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:Rs\.?|INR|₹)",
    r"(?:amount|total|due|pay(?:ment)?|penalty|fine|tax|charge|transfer|outstanding)"
    r"\b[^\d]{0,24}?(?:Rs\.?|INR|₹|■|(?<![A-Za-z])I)?\s*"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d{2}))(?!\.?\d)",
    # Symbol-prefixed figures with thousands separators (e.g. "■1,200").
    r"(?<![A-Za-z0-9.,])(?:[^\w\s]|(?<![A-Za-z])I(?=\d))?"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d{2}))(?!\.?\d)",
]

# Reference patterns. Labels are matched case-insensitively in a scoped group
# but the value itself must be UPPERCASE-with-separators, so "referencenumber90"
# can never become a reference.
_REF_LABEL_RE = re.compile(
    r"(?i:\b(?:reference|ref|policy|notice|case|file|ticket|invoice|order|acknowledg(?:e)?ment|claim)\b)"
    r"[\s.:#-]*"
    r"(?i:\b(?:no|number|num|id|ref)\b)?"
    r"[\s.:#-]*"
    r"\b([A-Z0-9][A-Z0-9]*(?:[-/][A-Z0-9]+)+)\b"
)
_STRUCT_ID_RE = re.compile(r"\b([A-Z]{2,}[A-Z0-9]*(?:-[A-Z0-9]+){2,})\b")
_SLASH_ID_RES = [
    re.compile(r"\b([A-Z]{2,4}/\d{4}/\d{2}/\d{4,6})\b"),
    re.compile(r"\b([A-Z]{2,4}/\d{4}/\d{4,6})\b"),
]

# Date role rules, evaluated in order against the matched date's own sentence.
DATE_ROLE_RULES: list[tuple[str, list[str]]] = [
    (
        "payment_deadline",
        [
            "payment deadline",
            "payment due",
            "pay by",
            "payable by",
            "due by",
            "due on",
            "due date",
            "make payment",
            "payment must",
            "must pay",
            "settle by",
            "remit by",
            "amount due",
        ],
    ),
    (
        "appeal_deadline",
        [
            "appeal",
            "internal review",
            "request a review",
            "review request",
            "dispute the decision",
            "dispute this",
            "challenge the",
        ],
    ),
    (
        "response_deadline",
        [
            "respond by",
            "reply by",
            "response deadline",
            "response due",
            "submit by",
            "return by",
            "contact us by",
            "provide by",
            "respond within",
            "reply within",
        ],
    ),
    ("hearing", ["hearing", "court date"]),
    (
        "issue",
        [
            "issue date",
            "date of issue",
            "date of letter",
            "letter date",
            "date of this letter",
            "date of notice",
            "notice date",
            "issued on",
            "date:",
        ],
    ),
    (
        "incident",
        [
            "incident",
            "occurred",
            "happened on",
            "was parked",
            "on or about",
            "took place",
            "collision",
            "accident",
        ],
    ),
]

DATE_ROLE_LABELS = {
    "payment_deadline": "Payment deadline",
    "appeal_deadline": "Appeal deadline",
    "response_deadline": "Response deadline",
    "hearing": "Hearing date",
    "issue": "Issue date",
    "incident": "Incident date",
    "informational": "Informational date",
}

_DATE_PARSE_SETTINGS = {
    "PREFER_DAY_OF_MONTH": "first",
    "PREFER_DATES_FROM": "future",
    "DATE_ORDER": "DMY",
    "RELATIVE_BASE": datetime.now(),
}


async def extract_facts(text: str, pages: list[dict]) -> list[Fact]:
    """Extract all deterministic facts from text."""
    facts: list[Fact] = []
    facts.extend(_extract_dates(text, pages))
    facts.extend(_extract_amounts(text, pages))
    facts.extend(_extract_references(text, pages))
    facts.extend(_extract_sender(text, pages))
    return facts


def _extract_dates(text: str, pages: list[dict]) -> list[Fact]:
    """Extract dates with sentence-scoped role classification."""
    facts: list[Fact] = []
    seen: set[tuple[str, str]] = set()

    for pattern in DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matched = match.group(0)
            candidate = re.sub(
                r"^(?:by|on|before|to)\s+", "", matched.strip(), flags=re.IGNORECASE
            )
            parsed = dateparser.parse(candidate, settings=_DATE_PARSE_SETTINGS)
            if not parsed:
                continue
            iso_date = parsed.strftime("%Y-%m-%d")

            sentence = _sentence_for(text, match.start(), match.end())
            role = _classify_date_role(sentence)
            if (iso_date, role) in seen:
                continue
            seen.add((iso_date, role))

            source, verification = _locate(matched, sentence, pages)
            if verification == VerificationStatus.NOT_FOUND:
                continue

            facts.append(
                Fact(
                    kind=FactKind.DATE,
                    label=DATE_ROLE_LABELS.get(role, "Date"),
                    raw_value=matched,
                    normalized_value=iso_date,
                    confidence=0.85
                    if verification == VerificationStatus.SUPPORTED
                    else 0.5,
                    source=source,
                    verification=verification,
                    role=role,
                )
            )

    return facts


def _extract_amounts(text: str, pages: list[dict]) -> list[Fact]:
    """Extract monetary amounts (currency- or label-grounded only)."""
    facts: list[Fact] = []
    seen_normalized: set[str] = set()

    for pattern in AMOUNT_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matched = match.group(0)
            amount_str = match.group(1) if match.lastindex else matched
            clean_amount = amount_str.replace(",", "").replace("₹", "").replace("Rs", "")
            try:
                amount_val = Decimal(clean_amount)
            except (InvalidOperation, ValueError):
                continue
            if amount_val == 0:
                continue

            normalized = f"{amount_val:.2f} INR"
            if normalized in seen_normalized:
                continue

            sentence = _sentence_for(text, match.start(), match.end())
            source, verification = _locate(matched, sentence, pages)
            if verification == VerificationStatus.NOT_FOUND:
                continue

            seen_normalized.add(normalized)
            facts.append(
                Fact(
                    kind=FactKind.AMOUNT,
                    label=_infer_amount_label(sentence),
                    raw_value=matched,
                    normalized_value=normalized,
                    confidence=0.85
                    if verification == VerificationStatus.SUPPORTED
                    else 0.5,
                    source=source,
                    verification=verification,
                )
            )

    return facts


def _extract_references(text: str, pages: list[dict]) -> list[Fact]:
    """Extract reference numbers (label-grounded or structured IDs)."""
    facts: list[Fact] = []
    seen_normalized: set[str] = set()

    matchers = [_REF_LABEL_RE, _STRUCT_ID_RE, *_SLASH_ID_RES]
    for matcher in matchers:
        for match in matcher.finditer(text):
            value = match.group(1)
            # Skip IDs truncated mid-token (e.g. "DPS-TEST-??" -> "DPS-TEST").
            next_char = text[match.end() : match.end() + 1]
            if next_char in ("-", "/"):
                continue
            if value in seen_normalized or not _plausible_ref(value):
                continue

            sentence = _sentence_for(text, match.start(), match.end())
            source, verification = _locate(match.group(0), sentence, pages)
            if verification == VerificationStatus.NOT_FOUND:
                continue

            seen_normalized.add(value)
            facts.append(
                Fact(
                    kind=FactKind.REFERENCE,
                    label="Reference number",
                    raw_value=match.group(0),
                    normalized_value=value,
                    confidence=0.9
                    if verification == VerificationStatus.SUPPORTED
                    else 0.5,
                    source=source,
                    verification=verification,
                )
            )

    return facts


def _extract_sender(text: str, pages: list[dict]) -> list[Fact]:
    """Extract sender/organization name (heuristic, claimed not verified)."""
    facts: list[Fact] = []

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
        if not any(kw in line_lower for kw in sender_keywords):
            continue
        candidate = line.strip()
        # Letterhead lines are short; second-person sentences are body text.
        if not candidate or len(candidate) > 120:
            continue
        if re.search(r"\byou\b|\byour\b", line_lower):
            continue
        source, verification = _locate(candidate, candidate, pages)
        if verification == VerificationStatus.NOT_FOUND:
            break
        facts.append(
            Fact(
                kind=FactKind.SENDER,
                label="Sender",
                raw_value=candidate,
                normalized_value=candidate,
                confidence=0.7
                if verification == VerificationStatus.SUPPORTED
                else 0.5,
                source=source,
                verification=verification,
                role="claimed_sender",
            )
        )
        break

    return facts


def _sentence_for(text: str, start: int, end: int, max_len: int = 400) -> str:
    """Return the sentence containing [start, end)."""
    left = start
    while left > 0 and text[left - 1] not in ".!?\n":
        left -= 1
    right = end
    while right < len(text) and text[right] not in ".!?\n":
        right += 1
    if right < len(text):
        right += 1
    return text[left:right].strip()[:max_len]


def _classify_date_role(sentence: str) -> str:
    """Classify a date's role from its own sentence only."""
    s = sentence.lower()
    for role, keywords in DATE_ROLE_RULES:
        if any(kw in s for kw in keywords):
            return role
    return "informational"


def _plausible_ref(value: str) -> bool:
    """Reject fragments, plain numbers, and date-like strings."""
    if len(value) < 5:
        return False
    if not re.search(r"\d", value):
        return False
    if not re.search(r"[-/]", value):
        return False
    if re.match(r"^\d{1,2}[-/]", value):  # looks like a date fragment
        return False
    return True


def _locate(
    matched: str, sentence: str, pages: list[dict]
) -> tuple[SourceSpan, VerificationStatus]:
    """Locate matched value in the source pages.

    Returns a span quoting the containing sentence when possible, plus the
    verification status. NOT_FOUND means the raw value is absent from the
    source and the fact must be dropped.
    """
    if not pages:
        return (
            SourceSpan(page=1, text=(sentence or matched)[:400], bbox=None),
            VerificationStatus.UNCERTAIN,
        )

    for page in pages:
        page_text = page.get("text", "")
        if matched not in page_text:
            continue
        quote = sentence if sentence and sentence in page_text else matched
        bbox = None
        for item in page.get("bbox_data", []):
            item_text = item.get("text", "")
            if (
                matched.lower() in item_text.lower()
                or item_text.lower() in matched.lower()
            ) and item_text.strip():
                b = item.get("bbox")
                if b:
                    bbox = BoundingBox(**b)
                    break
        return (
            SourceSpan(page=page.get("page_num", 1), text=quote[:400], bbox=bbox),
            VerificationStatus.SUPPORTED,
        )

    return (
        SourceSpan(page=1, text=(sentence or matched)[:400], bbox=None),
        VerificationStatus.NOT_FOUND,
    )


def _infer_amount_label(sentence: str) -> str:
    """Infer label for amount from its own sentence."""
    s = sentence.lower()

    if any(kw in s for kw in ["penalty", "fine"]):
        return "Penalty amount"
    if any(kw in s for kw in ["tax", "gst"]):
        return "Tax amount"
    if any(kw in s for kw in ["claim", "approved", "payable"]):
        return "Claim amount"
    if any(kw in s for kw in ["due", "outstanding", "amount due"]):
        return "Amount due"
    if any(kw in s for kw in ["refund", "credit"]):
        return "Refund amount"
    return "Amount"
