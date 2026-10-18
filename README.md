# Letter Decoder

A local-first, open-source app that explains official letters (tax notices, fines, insurance rejections, bank letters, landlord notices) in plain language. Runs entirely on your device with open-weight models via Ollama. No cloud calls, no telemetry, no accounts.

## The Feeling We're Building

> "A patient friend read it for me, and now I know what to do."

## Features

- **One input**: Drop a photo, PDF, screenshot, or paste text
- **Auto-detect**: Language, country, sender, notice type inferred from letter
- **Answer card**: 1-line verdict, deadline countdown, severity, 3 next steps, document checklist, editable draft reply
- **Source traceability**: Every date/amount links to exact line in original letter
- **Fully offline**: Works with internet turned off
- **Open weights**: Swap models, fine-tune locally, no vendor lock-in

## Architecture

```
[Input] → Preprocess → Extract Text → Deterministic Facts → Classify → Notice Pack → LLM Explain → Verify → Answer
```

**Key principle**: Code finds facts (dates, amounts, references), model explains them. The model never invents a deadline.

## Stack

- **Engine**: Python 3.11+, FastAPI, pydantic v2, OpenCV, Tesseract, dateparser
- **Inference**: Ollama (qwen2.5:7b or any compatible model)
- **Storage**: Encrypted SQLite (planned), .ics calendar export
- **Contract**: JSON Schema + pydantic models → OpenAPI, examples, SSE events

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (fast Python package manager)
- [Ollama](https://ollama.ai) (for real engine mode)

### Install

```bash
# Clone and enter
git clone <repo-url>
cd letter-decoder

# Install dependencies
uv sync --all-extras

# Pull model (for real mode)
ollama pull qwen2.5:7b
```

### Run in Mock Mode (no Ollama needed)

```bash
ENGINE_MODE=mock uv run python -m api.main
```

Open `http://127.0.0.1:8000/dev-ui` for the test harness.

### Run with Real Engine

```bash
# Terminal 1: Start Ollama
ollama serve

# Terminal 2: Run API
uv run python -m api.main
```

## Project Structure

```
letter-decoder/
├── api/                    # FastAPI application
│   └── main.py            # API routes, SSE, mock mode
├── contract/              # Contract (source of truth)
│   ├── models.py          # Pydantic models
│   ├── schema.py          # JSON Schema generation
│   ├── events.md          # SSE event specification
│   └── examples/          # Example answers for all states
├── engine/                # Pure pipeline library
│   ├── pipeline.py        # Main orchestrator
│   ├── preprocess.py      # OpenCV deskew/denoise
│   ├── extract_text.py    # PDF text + OCR
│   ├── deterministic_extract.py  # Regex + dateparser
│   ├── classifier.py      # Keyword/embedding matching
│   ├── pack_loader.py     # Notice pack YAML loader
│   ├── llm_constrained.py # JSON-constrained LLM output
│   └── verifier.py        # Fact verification
├── dev-ui/                # Throwaway HTML/JS test harness
├── notices/               # Notice packs by country
│   └── XX/placeholder.yaml
├── templates/             # Reply templates by language
├── samples/               # Anonymized test letters
├── eval/                  # Accuracy evaluation scripts
├── docs/                  # UI_HANDOFF.md, etc.
├── tests/                 # Contract + unit tests
└── pyproject.toml
```

## Contract-First Development

The `/contract` directory is the single source of truth:

- `models.py` — Pydantic models for all API types
- `answer.schema.json` — Generated JSON Schema (committed)
- `openapi.json` — Generated OpenAPI spec (committed)
- `events.md` — SSE event order and payloads
- `examples/*.json` — Canonical examples for every UI state

**UI agent reads only** `/contract` and `/docs/UI_HANDOFF.md`.

## Mock Mode

`ENGINE_MODE=mock` replays `/contract/examples` through the same endpoints with realistic delays. Use for UI development without a model.

## Local-Only Enforcement

- API binds to `127.0.0.1:8000`
- CORS allows only `localhost:5173`, `127.0.0.1:5173`
- Test suite fails if any outbound network call attempted

## Testing

```bash
# All tests
uv run pytest

# Contract tests only
uv run pytest tests/contract_tests.py -v

# Local-only tests
uv run pytest tests/test_local_only.py -v

# Deterministic extraction tests
uv run pytest tests/test_deterministic_extract.py -v
```

## Contributing (Hacktoberfest)

Most contributions are **data, not code**:

1. **Notice packs**: `/notices/<country>/<type>.yaml`
2. **Reply templates**: `/templates/<lang>.yaml`
3. **Sample letters**: `/samples/<country>/<type>/`
3. **UI locales**: `/app/src/locales/<lang>.json`

All validated by CI against JSON Schema.

See `CONTRIBUTING.md` for details.

## Why Open Models Matter

| Aspect | Closed API | Letter Decoder (Open) |
|--------|------------|----------------------|
| **Privacy** | Letters uploaded | Never leaves device |
| **Cost** | Per-page fees | Zero marginal cost |
| **Control** | Vendor roadmap | Swap/fine-tune models |
| **Lock-in** | Account required | No accounts, ever |
| **Audit** | Trust me | Open source, verifiable |

## License

MIT License — see `LICENSE` file.

## Security

- No telemetry, no analytics, no phoning home
- Encrypted local storage (planned)
- Report vulnerabilities via GitHub Security Advisories

## Disclaimer

**Not legal or tax advice.** AI-generated content is always labeled. Consult a qualified professional for legal, tax, or financial matters.