"""Contract tests: validate engine output and mock output against schema."""

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from contract.models import ANSWER_SCHEMA_VERSION, Answer
from contract.schema import get_answer_schema

CONTRACT_DIR = Path("contract")
EXAMPLES_DIR = CONTRACT_DIR / "examples"
SCHEMA = get_answer_schema()


def load_example(name: str) -> dict:
    """Load example JSON file."""
    path = EXAMPLES_DIR / f"{name}.json"
    if not path.exists():
        pytest.skip(f"Example not found: {name}")
    with open(path) as f:
        return json.load(f)


@pytest.mark.parametrize(
    "example_name",
    [
        "routine",
        "act_soon",
        "see_professional",
        "low_confidence_blurry",
        "no_deadline_found",
        "clarifying_question",
        "null_bbox",
        "verified_false",
    ],
)
def test_example_validates_against_schema(example_name):
    """Each example must validate against the answer schema."""
    data = load_example(example_name)
    try:
        validate(instance=data, schema=SCHEMA)
    except ValidationError as e:
        pytest.fail(f"{example_name}.json validation failed: {e.message}")


def test_error_examples_exist():
    """All typed error examples must exist."""
    error_codes = [
        "unsupported_file",
        "unreadable_image",
        "ocr_failed",
        "model_unavailable",
        "timeout",
        "internal",
    ]
    for code in error_codes:
        path = EXAMPLES_DIR / f"error_{code}.json"
        assert path.exists(), f"Missing error example: {code}"


def test_full_sequence_exists():
    """Full SSE sequence example must exist."""
    path = EXAMPLES_DIR / "events" / "full_sequence.ndjson"
    assert path.exists(), "Missing full_sequence.ndjson"

    # Validate each line is valid JSON
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    json.loads(line)
                except json.JSONDecodeError as e:
                    pytest.fail(f"Line {i} in full_sequence.ndjson is invalid JSON: {e}")


def test_schema_version_consistency():
    """Schema version in examples must match ANSWER_SCHEMA_VERSION."""
    for example_file in EXAMPLES_DIR.glob("*.json"):
        if example_file.name.startswith("error_"):
            continue  # Errors don't have schema_version
        with open(example_file) as f:
            data = json.load(f)
        if "schema_version" in data:
            assert data["schema_version"] == ANSWER_SCHEMA_VERSION, (
                f"{example_file.name}: schema_version mismatch"
            )


def test_answer_model_instantiation():
    """Answer model can be instantiated from routine example."""
    data = load_example("routine")
    answer = Answer(**data)
    assert answer.id == "ex_routine_001"
    assert answer.status.value == "ready"
    assert len(answer.facts) == 3


def test_mock_mode_can_load_examples():
    """Engine mock mode can load all examples."""

    from engine.pipeline import LetterDecoderPipeline

    pipeline = LetterDecoderPipeline(engine_mode="mock")

    for example_name in [
        "routine",
        "act_soon",
        "see_professional",
        "low_confidence_blurry",
        "no_deadline_found",
        "clarifying_question",
    ]:
        answer = pipeline.load_mock_example(example_name)
        assert isinstance(answer, Answer)
        assert answer.schema_version == ANSWER_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_mock_process_yields_events():
    """Mock process yields expected event sequence."""
    from engine.pipeline import LetterDecoderPipeline

    pipeline = LetterDecoderPipeline(engine_mode="mock")
    events = []

    async for event in pipeline.process_mock("routine"):
        events.append(event)

    event_types = [e["event"] for e in events]
    expected_order = [
        "stage",
        "stage",
        "stage",
        "facts",
        "stage",
        "classification",
        "stage",
        "deadline",
        "severity",
        "verdict",
        "stage",
        "explanation",
        "steps",
        "checklist",
        "big_print",
        "stage",
        "done",
    ]

    # Check order (allow extra stages)
    idx = 0
    for expected in expected_order:
        while idx < len(event_types) and event_types[idx] != expected:
            idx += 1
        assert idx < len(event_types), f"Missing event: {expected}"
        idx += 1


def test_openapi_matches_schema():
    """OpenAPI spec should be generable from models."""
    from api.main import app

    openapi_schema = app.openapi()
    assert "components" in openapi_schema
    assert "schemas" in openapi_schema["components"]
    assert "Answer" in openapi_schema["components"]["schemas"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
