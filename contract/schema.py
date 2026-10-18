"""JSON Schema generation for the Answer model."""

import json
from pathlib import Path

from .models import ANSWER_SCHEMA_VERSION, Answer


def get_answer_schema() -> dict:
    """Generate JSON Schema from the Answer model."""
    schema = Answer.model_json_schema()
    schema["$id"] = "https://letter-decoder.local/schema/answer.json"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Letter Decoder Answer"
    schema["description"] = "Complete answer card for a processed official letter"
    return schema


def write_schema_files(contract_dir: Path) -> None:
    """Write schema files to the contract directory."""
    schema = get_answer_schema()

    # Write answer.schema.json
    schema_path = contract_dir / "answer.schema.json"
    schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False))

    # Write schema version
    version_path = contract_dir / "schema_version.txt"
    version_path.write_text(ANSWER_SCHEMA_VERSION)


if __name__ == "__main__":
    contract_dir = Path(__file__).parent
    write_schema_files(contract_dir)
    print(f"Schema written to {contract_dir / 'answer.schema.json'}")
    print(f"Version: {ANSWER_SCHEMA_VERSION}")
