# Letter Decoder

> "A patient friend read it for me, and now I know what to do."

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Hacktoberfest 2026](https://img.shields.io/badge/Hacktoberfest-2026-orange.svg)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Ollama](https://img.shields.io/badge/Inference-Ollama-black)
![Offline](https://img.shields.io/badge/Runs-100%25%20offline-brightgreen)

**A local-first, open-source app that explains official letters in plain language.**

Tax notices, fines, insurance rejections, bank letters, landlord notices — drop one in as a
photo, PDF, screenshot, or pasted text, and get back an **answer card**: a one-line verdict, a
deadline countdown, severity, three concrete next steps, a document checklist, and an editable
draft reply. Every date and amount links back to the exact line of the original letter it came
from.

No cloud calls. No telemetry. No accounts. **The letter never leaves your device.**

---

## Live Demo

| | URL | What it is |
|---|---|---|
| **Frontend** | https://letter-decoder.vercel.app | React app (Vercel) |
| **API** | https://letter-decoder-api.onrender.com | FastAPI engine (Render) |

> The public API runs `ENGINE_MODE=mock`, replaying canonical examples through the same
> endpoints and SSE event streams with realistic delays. For real decoding with an open-weight
> model, run it locally with Ollama — see [Quick Start](#quick-start).

---

## The Problem

An official letter arrives. It is written in a register you were never taught — statute
numbers, reference codes, "failure to comply may result in…" — and somewhere inside is a date
that changes your life if you miss it.

You have three options: pay a professional $150–300 to read it to you, guess, or freeze.
Letter Decoder is the fourth option: a patient friend that runs on your own machine, reads the
letter with an open-weight model, and tells you — with receipts — what it means and what to do
next.

---

## Features

- **One input** — photo, PDF, screenshot, or paste text
- **Auto-detect** — language, country, sender, and notice type inferred from the letter
- **Answer card** — verdict, deadline countdown, severity, next steps, checklist, draft reply
- **Source traceability** — every date and amount links to the exact line in the original
- **Calendar export** — deadlines as `.ics` reminders
- **Fully offline** — works with the internet turned off; enforced by the test suite
- **Open weights** — swap models, fine-tune locally, no vendor lock-in

---

## Architecture

```
[Input] → Preprocess → Extract Text → Deterministic Facts → Classify → Notice Pack → LLM Explain → Verify → Answer
```

### The iron rule: code finds facts, the model explains them

Dates, amounts, and reference numbers are extracted **deterministically** (regex +
`dateparser`). The LLM never invents a deadline: it only produces structure, plain-language
explanation, and a draft reply — and a verifier then checks every factual claim against the
extracted facts. If verification fails, you get a clean error, not a confident lie.

```
engine/            pure pipeline library (no web, no UI)
  preprocess.py        OpenCV deskew/denoise
  extract_text.py      PDF text + Tesseract OCR
  deterministic_extract.py   regex + dateparser
  classifier.py        keyword/embedding matching
  pack_loader.py       notice-pack YAML loader
  llm_constrained.py   JSON-constrained LLM output
  verifier.py          fact verification
contract/          single source of truth (models → schema → OpenAPI → examples)
api/               FastAPI routes + SSE event bus
app/               React 19 frontend (Decode, History, Notice Packs, Settings)
dev-ui/            throwaway HTML/JS test harness served at /dev-ui
notices/           notice packs by country (YAML)
templates/         reply templates by language
tests/             contract + unit + local-only enforcement tests
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (fast Python package manager)
- [Ollama](https://ollama.ai) — only for real-engine mode

### 1. Mock mode (no model needed)

```bash
git clone https://github.com/RAMBO-LC/letter-decoder.git
cd letter-decoder
uv sync --all-extras

ENGINE_MODE=mock uv run python -m api.main
```

Open `http://127.0.0.1:8000` for the app, or `http://127.0.0.1:8000/dev-ui` for the test
harness. Mock mode replays `/contract/examples` through the same endpoints with realistic
delays — ideal for UI work without a model.

### 2. Real engine with Ollama

```bash
# Terminal 1
ollama serve
ollama pull qwen2.5:7b

# Terminal 2
uv run python -m api.main
```

Any Ollama-compatible model works — change `MODEL_NAME` to swap `qwen2.5:7b` for Gemma, Llama,
or a fine-tuned checkpoint.

### 3. Docker

```bash
docker build -t letter-decoder .
docker run -p 8000:8000 -e ENGINE_MODE=mock letter-decoder
```

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Engine mode, model availability |
| `POST` | `/api/letters` | Upload a letter (file, text, or sample) |
| `GET` | `/api/letters/{id}/events` | SSE stream: stage → facts → verdict → done |
| `GET` | `/api/letters/{id}` | Full answer object |
| `GET` | `/api/letters` | List processed letters |
| `POST` | `/api/letters/{id}/draft` | Draft reply in `neutral` / `polite` / `firm` |
| `GET` | `/api/letters/{id}/reminder.ics` | Deadline as a calendar file |
| `PATCH` | `/api/letters/{id}/steps/{step}` | Mark a next-step done |
| `DELETE` | `/api/letters/{id}` | Delete a letter and its data |
| `GET` | `/api/packs` | Installed notice packs |

Full OpenAPI spec: `contract/openapi.json` (generated from the pydantic models).

---

## Contract-First Development

`/contract` is the single source of truth:

- `models.py` — pydantic models for every API type
- `answer.schema.json` — generated JSON Schema (committed)
- `openapi.json` — generated OpenAPI spec (committed)
- `events.md` — SSE event order and payloads
- `examples/` — canonical answers for **14 UI states** (routine, act-soon,
  see-a-professional, low-confidence, clarifying question, and every error state)

The frontend reads only `/contract` and `/docs/UI_HANDOFF.md`. `ENGINE_MODE=mock` replays the
examples, so UI development never needs a running model.

---

## Privacy, Enforced in CI

Not a policy — a test suite:

- API binds to `127.0.0.1:8000` locally (`0.0.0.0` only when a platform sets `PORT`)
- CORS allows only localhost origins unless `CORS_ORIGINS` is explicitly set
- `tests/test_local_only.py` **fails the build if any code path attempts an outbound network
  call**
- No telemetry, no analytics, no phoning home
- Uploaded letters live in `data/uploads/` (git-ignored; never committed)

---

## Contributing (Hacktoberfest 2026)

Most contributions are **data, not code**:

1. **Notice packs** — `notices/<country>/<type>.yaml`
2. **Reply templates** — `templates/<lang>.yaml`
3. **Sample letters** — `samples/<country>/<type>/`
4. **UI locales** — `app/src/locales/<lang>.json`

All validated by CI against JSON Schema. Adding a country is a YAML file, not a Python PR.
See [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

---

## Why Open Models Matter

| Aspect | Closed API | Letter Decoder (open) |
|--------|------------|----------------------|
| **Privacy** | Letters uploaded to someone's server | Never leaves your device |
| **Cost** | Per-page / per-token fees | Zero marginal cost |
| **Control** | Vendor roadmap | Swap or fine-tune models |
| **Lock-in** | Account required | No accounts, ever |
| **Audit** | "Trust us" | Open source, verifiable |

A letter contains income, legal status, financial history. With a closed API, explaining it
means uploading it. There is no setting or enterprise tier that un-does that. With an open
local model, the letter structurally never leaves the machine — and the verifier that proves
"the model never invents a deadline" is code you can read.

---

## License

[MIT](LICENSE).

**Disclaimer: not legal or tax advice.** AI-generated content is always labeled. Consult a
qualified professional for legal, tax, or financial matters.

## Security

Report vulnerabilities via [GitHub Security Advisories](../../security/advisories).
