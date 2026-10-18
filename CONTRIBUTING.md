# Contributing to Letter Decoder

Thank you for contributing! This project is designed so most contributions are **data, not code** — validated by CI against JSON Schema.

## Ways to Contribute

### 1. Add a Notice Pack (Good First Issue)

Create `/notices/<COUNTRY>/<type>.yaml`:

```yaml
id: "in_gst_payment_reminder"
names: ["GST Payment Reminder", "GST Notice"]
keywords: ["gst", "goods and services tax", "payment", "reminder", "due"]
sender: "GST Department"
country: "IN"
language: "en"
meaning: "A reminder to pay outstanding GST liability."
severity: "routine"
severity_reason: "Standard payment reminder, typically 14+ days notice"
deadline_rule: "latest_date"
checklist:
  - "GST return for the relevant period"
  - "Payment challan"
reply_templates:
  en:
    neutral: "Thank you for the reminder. I have noted the payment due and will process it shortly."
    polite: "I kindly acknowledge receipt of your GST payment reminder. I will make the payment by the due date."
    firm: "I have received the GST notice. I am verifying the amount and will respond within the statutory period."
source_urls:
  - "https://www.gst.gov.in/"
```

### 2. Add Reply Templates

Add `/templates/<lang>.yaml` with `neutral`, `polite`, `firm` variants.

### 3. Add Sample Letters

Add 3 anonymized letters per notice type in `/samples/<COUNTRY>/<type>/`:
- `letter_1.png` / `.pdf` / `.txt`
- `expected.json` (expected Answer output)

### 4. Add UI Locale

Add `/app/src/locales/<lang>.json` with all UI strings.

### 5. Improve Extractors

Add date/amount/reference patterns in `engine/deterministic_extract.py`.

### 6. Translate Documentation

Translate `README.md`, `CONTRIBUTING.md`, or UI strings.

## Development Setup

```bash
# Install with dev dependencies
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest

# Run contract tests
uv run pytest tests/contract_tests.py -v
```

## Pull Request Process

1. Fork the repo
2. Create a branch: `feat/add-in-gst-notice` or `fix/date-parser`
3. Make your changes
4. Run tests: `uv run pytest`
5. For data changes, CI validates against schema automatically
6. Open PR with clear description

## Good First Issues

| Issue | Labels | Description |
|-------|--------|-------------|
| Add notice pack for IN income tax notice | `hacktoberfest`, `good first issue`, `data` | Create `/notices/IN/in_income_tax_notice.yaml` |
| Add Hindi UI locale | `hacktoberfest`, `good first issue`, `i18n` | Create `/app/src/locales/hi.json` |
| Add 3 synthetic GST sample letters | `hacktoberfest`, `good first issue`, `data` | Add to `/samples/IN/gst_payment_reminder/` |
| Improve date parser for DD-Mon-YY format | `hacktoberfest`, `good first issue`, `code` | Update `engine/deterministic_extract.py` |
| Add reply templates for Marathi | `hacktoberfest`, `good first issue`, `i18n` | Create `/templates/mr.yaml` |
| Add keyboard navigation test | `hacktoberfest`, `good first issue`, `a11y` | Add Playwright test for tab order |
| Add missing alt label to dev-ui | `hacktoberfest`, `good first issue`, `a11y` | Fix accessibility in `dev-ui/index.html` |
| Translate README to Spanish | `hacktoberfest`, `good first issue`, `docs` | Create `README.es.md` |
| Add date format to extractor tests | `hacktoberfest`, `good first issue`, `test` | Add test case in `tests/test_deterministic_extract.py` |
| Add stamp SVG for Devanagari | `hacktoberfest`, `good first issue`, `design` | Create SVG for "Handled" stamp in Hindi |

## Code Style

- Python: `ruff` (lint + format), `mypy` (strict)
- Commits: Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`)
- Test, then commit — never commit broken state

## Schema Validation

All YAML/JSON data files are validated in CI:

```bash
# Validate notice packs
uv run python -c "import yaml; yaml.safe_load(open('notices/IN/in_gst_notice.yaml'))"

# Validate against JSON Schema
uv run pytest tests/contract_tests.py::test_example_validates_against_schema
```

## Questions?

Open a GitHub Discussion or check `/docs/UI_HANDOFF.md` for engine contract details.