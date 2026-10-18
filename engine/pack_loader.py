"""Notice pack loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


async def load_notice_pack(
    notice_type_id: str,
    country: str,
    notices_dir: Path,
) -> dict[str, Any]:
    """Load notice pack by type ID and country."""
    pack_path = notices_dir / country.upper() / f"{notice_type_id}.yaml"

    if not pack_path.exists():
        # Return default/empty pack
        return {
            "id": notice_type_id,
            "severity": "routine",
            "severity_reason": "Default severity",
            "deadline_rule": "latest_date",
            "checklist": [],
            "reply_templates": {},
            "mock_simple": "This is a mock explanation.",
            "mock_detailed": "Detailed mock explanation for testing.",
            "mock_big_print_1": "Mock line 1",
            "mock_big_print_2": "Mock line 2",
        }

    with open(pack_path) as f:
        return yaml.safe_load(f)
