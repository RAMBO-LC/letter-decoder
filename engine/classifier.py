"""Letter classifier using keyword/embedding matching against notice packs."""

from __future__ import annotations

from pathlib import Path

import yaml

from contract.models import Classification, Fact


async def classify_letter(
    text: str,
    facts: list[Fact],
    country: str,
    language: str,
    notices_dir: Path,
) -> Classification:
    """Classify letter against notice packs."""
    text_lower = text.lower()
    country_dir = notices_dir / country.upper()

    pack_dirs = [country_dir] if country_dir.exists() else []
    if not pack_dirs:
        # Cross-country fallback: score every pack rather than silently
        # returning unknown with zero confidence.
        pack_dirs = [d for d in notices_dir.glob("*") if d.is_dir()]

    candidates = []

    for current_dir in pack_dirs:
        for pack_file in current_dir.glob("*.yaml"):
            try:
                with open(pack_file) as f:
                    pack = yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError):
                continue

            notice_type_id = pack.get("id", pack_file.stem)
            keywords = pack.get("keywords", [])
            names = pack.get("names", [])

            keyword_score = 0
            for kw in keywords:
                if kw.lower() in text_lower:
                    keyword_score += 1

            name_score = 0
            for name in names:
                if name.lower() in text_lower:
                    name_score += 2  # Names weighted higher

            sender_score = 0
            sender_facts = [f for f in facts if f.kind.value == "sender"]
            for sf in sender_facts:
                sender_text = (
                    sf.normalized_value.lower() if sf.normalized_value else sf.raw_value.lower()
                )
                for name in names:
                    if name.lower() in sender_text:
                        sender_score += 3

            total_score = keyword_score + name_score + sender_score
            max_possible = len(keywords) + len(names) * 2 + len(sender_facts) * 3
            confidence = (
                min(total_score / max(max_possible, 1), 1.0) if max_possible > 0 else 0.0
            )

            if confidence > 0:
                candidates.append(
                    {
                        "notice_type_id": notice_type_id,
                        "confidence": confidence,
                        "sender": pack.get("sender"),
                        "country": current_dir.name,
                    }
                )

    candidates.sort(key=lambda x: x["confidence"], reverse=True)

    if not candidates:
        return Classification(
            notice_type_id="unknown",
            country=country,
            language=language,
            sender=_claimed_sender(facts),
            confidence=0.0,
        )

    best = candidates[0]
    sender = best.get("sender")
    if not sender or sender.strip().lower() in {"unknown sender", "unknown", "n/a"}:
        sender = _claimed_sender(facts)
    return Classification(
        notice_type_id=best["notice_type_id"],
        country=country,
        language=language,
        sender=sender,
        confidence=best["confidence"],
        top_candidates=candidates[:3],
    )


def _claimed_sender(facts: list[Fact]) -> str | None:
    """Fall back to the sender line extracted from the letter itself."""
    for f in facts:
        if f.kind.value == "sender":
            return f.normalized_value or f.raw_value
    return None
