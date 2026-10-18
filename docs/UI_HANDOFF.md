# UI Handoff Document

This document describes how the UI agent should integrate with the Letter Decoder engine API.

## Quick Start

### Run in Mock Mode (no Ollama required)

```bash
ENGINE_MODE=mock uv run python -m api.main
```

The API will be available at `http://127.0.0.1:8000`

### Dev Harness

Open `http://127.0.0.1:8000/dev-ui` in a browser to test the API with a simple vanilla HTML interface.

### Run with Real Engine (requires Ollama)

```bash
# Install and start Ollama
ollama pull qwen2.5:7b
ollama serve

# Run API
uv run python -m api.main
```

## API Endpoints

### Health Check
```
GET /api/health
```
Returns engine status, model availability, and mock mode flag.

### Upload Letter
```
POST /api/letters
Content-Type: multipart/form-data

Fields:
- file: (optional) image or PDF
- text: (optional) plain text
- country: (default "XX") country code
- language: (default "en") language code
```

Returns: `{ "id": "abc123", "status": "queued" }`

### SSE Event Stream
```
GET /api/letters/{id}/events
```
Server-Sent Events stream. See [Event Types](#event-types) below.

### Get Full Answer
```
GET /api/letters/{id}
```
Returns complete Answer object.

### List Letters
```
GET /api/letters
```
Returns array of letter summaries.

### Update Step
```
PATCH /api/letters/{id}/steps/{step_id}
Content-Type: application/json

{ "done": true }
```

### Generate Draft Reply
```
POST /api/letters/{id}/draft?tone=neutral|polite|firm
```
Returns DraftReplies with requested tone.

### User Correction
```
POST /api/letters/{id}/correct
Content-Type: application/json

{ "correction": "..." }
```

### Get Original Image
```
GET /api/letters/{id}/image
```

### Get Calendar Reminder
```
GET /api/letters/{id}/reminder.ics
```
Returns `.ics` file for the deadline.

### Delete Letter
```
DELETE /api/letters/{id}
```

## Event Types (SSE)

Events arrive in this order:

| Event | Description | Data |
|-------|-------------|------|
| `stage` | Pipeline stage progress | `{stage, progress}` |
| `facts` | **FIRST** - deterministic facts with bboxes | `{facts: Fact[]}` |
| `classification` | Letter type classification | `Classification` |
| `deadline` | Identified deadline | `Deadline` |
| `severity` | Severity assessment | `Severity` |
| `verdict` | One-line verdict | `Verdict` |
| `explanation` | Simple + detailed explanation | `Explanation` |
| `steps` | Up to 3 next steps | `{steps: Step[]}` |
| `checklist` | Documents to gather | `{checklist: ChecklistItem[]}` |
| `big_print` | Large-print summary lines | `BigPrint` |
| `warning` | Quality warnings (any time) | `Warning` |
| `clarifying_question` | Single question with chips | `ClarifyingQuestion` |
| `done` | Full final answer | `Answer` |
| `error` | Typed error | `ErrorResponse` |

### Event Details

#### `facts` (MUST render first)
```json
{
  "facts": [
    {
      "id": "fact_1",
      "kind": "date|amount|reference|sender|other",
      "label": "Due date",
      "raw_value": "15 Nov 2024",
      "normalized_value": "2024-11-15",
      "confidence": 0.95,
      "verified": true,
      "source": {"page": 1, "text": "Payment due by 15 Nov 2024", "bbox": {"x": 0.1, "y": 0.4, "width": 0.35, "height": 0.04}}
    }
  ]
}
```
**UI MUST**: Draw bounding boxes on the letter image immediately when this event arrives.

#### `deadline`
```json
{"fact_id": "fact_1", "kind": "payment", "iso_date": "2024-11-15", "confidence": 0.9}
```
**UI computes**: Relative time ("in 5 days", "overdue by 2 days") client-side using `Intl.RelativeTimeFormat`.

#### `warning`
```json
{"code": "low_confidence_date", "message": "Date extracted with low confidence", "bbox": {...}}
```
Warning codes:
- `low_confidence_date` / `low_confidence_amount` — show amber "check this line" note
- `unreadable_region` — outline the region on the image
- `no_deadline_found` — show inline note, no countdown
- `verifier_mismatch` — LLM invented a date/amount; show warning
- `see_professional` — legal/medical/tax advice disclaimer

#### `clarifying_question`
```json
{"id": "cq_1", "text": "Is this for you or your company?", "options": ["Me", "My company", "Not sure"]}
```
**UI MUST**: Show as inline tap chips. Pause other rendering until user responds.

## States the UI Must Handle

| State | Trigger | UI Behavior |
|-------|---------|-------------|
| **Idle** | No letter uploaded | Show drop zone + "Try sample" buttons |
| **Uploading** | POST /api/letters | Show spinner |
| **Reading** | `stage: extract_text` | "Reading letter..." + progress |
| **Partial (facts only)** | `facts` event received | Show image with bbox overlays, "Finding dates..." |
| **Full answer** | `done` event | Render complete answer card |
| **Low confidence** | `warning: low_confidence_*` | Amber notes on affected facts |
| **Unreadable region** | `warning: unreadable_region` | Outline region on image |
| **No deadline** | `deadline.iso_date === null` | No countdown, show "No deadline found" note |
| **Clarifying question** | `clarifying_question` event | Inline chips, wait for tap |
| **Error** | `error` event or HTTP error | Show error message + retry button if `retryable: true` |
| **Engine down** | `/api/health` returns degraded | Banner: "Engine unavailable, using mock mode" |
| **Model missing** | `/api/health` model_available: false | Banner: "Local model not found. Start Ollama or use mock mode." |

## Answer Schema (Key Fields)

All human-readable text is in the user's language. No hardcoded UI strings.

```typescript
interface Answer {
  schema_version: "0.1.0";
  id: string;
  status: "queued" | "reading" | "ready" | "error";
  facts: Fact[];
  classification?: Classification;
  deadline?: Deadline;  // iso_date or null
  severity?: Severity;  // routine | act_soon | see_professional | unknown
  verdict?: Verdict;    // one sentence
  explanation?: { simple: string; detailed: string };
  steps: Step[];        // max 3, with checkboxes
  checklist: ChecklistItem[];
  draft_replies?: { neutral: string; polite?: string; firm?: string };
  big_print?: { lines: string[] };  // max 3 lines
  clarifying_question?: { id: string; text: string; options: string[] } | null;
  warnings: Warning[];
  meta: { engine_version, model, offline: true, timings_ms };
}
```

## Mock Examples

Pre-built examples in `/contract/examples/`:
- `routine.json` — standard payment reminder
- `act_soon.json` — penalty with near deadline
- `see_professional.json` — court summons
- `low_confidence_blurry.json` — blurry image warnings
- `no_deadline_found.json` — approval letter, no deadline
- `clarifying_question.json` — ambiguous ownership
- `null_bbox.json` — facts without bounding boxes
- `verified_false.json` — verifier caught mismatch
- `error_*.json` — typed error examples
- `events/full_sequence.ndjson` — complete SSE replay

## Local-Only Enforcement

- API binds to `127.0.0.1:8000` only
- CORS allows only `localhost:5173`, `127.0.0.1:5173`, and API origin
- Test in `/eval/test_local_only.py` fails if any outbound call detected

## Contract Tests

Run contract validation:
```bash
uv run pytest tests/contract_tests.py -v
```

Validates:
- Engine output matches `answer.schema.json`
- Mock output matches schema
- All required example files exist
- SSE event order is correct

## Files the UI Agent Owns

```
/app                          # React + TypeScript + Vite app
/app/src/locales/             # UI strings (contributors add languages)
```

## Files the UI Agent Reads (read-only)

```
/contract/answer.schema.json  # JSON Schema for Answer
/contract/openapi.json        # OpenAPI spec
/contract/events.md           # This event specification
/contract/examples/*.json     # Example answers for every state
/docs/UI_HANDOFF.md           # This document
```

## Requesting Contract Changes

Write to `/contract/REQUESTS.md` with:
- What field/event you need
- Why the current contract doesn't support it
- Proposed additive change (prefer adding optional fields)

The engine agent will respond within the same working session.

## Calm Mode

Apply calm mode (plain fades, no animations, no jokes) when:
- `severity.level === "see_professional"` or `"unknown"`
- Any `low_confidence_*` warning exists
- `verifier_mismatch` warning exists

## Accessibility Floor

- Touch targets ≥ 48px with ≥ 8px spacing
- Body text ≥ 18px, user-adjustable
- WCAG AA contrast (verify with tool)
- Never color alone for severity (icon + text + color)
- Visible focus states
- Focus returns to trigger after drawer/dialog closes
- Sonner undo toast ≥ 10s + inline Undo
- `speechSynthesis` read-aloud: only voices with `localService === true`

## Signature Moments (Optional)

1. **Highlighter**: Strokes draw over found dates/amounts
2. **Flight**: Facts animate into answer card (fallback: fade)
3. **Tick**: Step check animation
4. **Stamp**: "Handled" stamp when all steps done (text from locale)

All respect `prefers-reduced-motion`. Use `MotionConfig reducedMotion="user"`.

## Contact

Engine agent: check `/contract/REQUESTS.md` for change requests.