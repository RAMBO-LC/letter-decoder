# SSE Event Stream Specification

## Event Order (strict)

The engine emits SSE events in this exact order. The UI must handle them
sequentially and render partial state as each arrives.

```
stage         -> facts (deterministic, with bboxes, FIRST)
              -> classification
              -> deadline
              -> severity
              -> verdict
              -> explanation / steps / checklist / big_print (as ready, any order)
              -> warning (any time, multiple)
              -> done (full answer) | error (typed)
```

## Event Details

### `stage`
Signals the current pipeline stage.

```json
{
  "id": "evt_001",
  "event": "stage",
  "data": {"stage": "preprocess", "progress": 0.1}
}
```

Stages: `preprocess`, `extract_text`, `extract_facts`, `classify`, `load_pack`, `explain`, `verify`, `complete`

### `facts` (FIRST deterministic output)
All deterministically extracted facts with bounding boxes. This arrives BEFORE any LLM output.

```json
{
  "id": "evt_002",
  "event": "facts",
  "data": {
    "facts": [
      {
        "id": "fact_1",
        "kind": "date",
        "label": "Due date",
        "raw_value": "12 Nov 2024",
        "normalized_value": "2024-11-12",
        "confidence": 0.95,
        "verified": true,
        "source": {"page": 1, "text": "Pay by 12 Nov 2024", "bbox": {"x": 0.1, "y": 0.3, "width": 0.4, "height": 0.05}}
      }
    ]
  }
}
```

### `classification`
Letter type classification.

```json
{
  "id": "evt_003",
  "event": "classification",
  "data": {
    "notice_type_id": "in_gst_notice",
    "country": "IN",
    "language": "en",
    "sender": "GST Department",
    "confidence": 0.92,
    "top_candidates": [...]
  }
}
```

### `deadline`
Identified deadline (references a fact by id).

```json
{
  "id": "evt_004",
  "event": "deadline",
  "data": {
    "fact_id": "fact_1",
    "kind": "payment",
    "iso_date": "2024-11-12",
    "confidence": 0.9
  }
}
```

### `severity`
Severity assessment.

```json
{
  "id": "evt_005",
  "event": "severity",
  "data": {
    "level": "act_soon",
    "reason": "Payment due in 7 days",
    "confidence": 0.85
  }
}
```

### `verdict`
One-line verdict.

```json
{
  "id": "evt_006",
  "event": "verdict",
  "data": {"text": "GST Department says you owe ₹4,200. Pay by 12 Nov.", "confidence": 0.88}
}
```

### `explanation`
Plain-language explanation (simple + detailed).

```json
{
  "id": "evt_007",
  "event": "explanation",
  "data": {
    "simple": "You have a GST tax notice for ₹4,200 due on 12 Nov.",
    "detailed": "The notice states that your GST return for Q3 shows a mismatch..."
  }
}
```

### `steps`
Up to 3 next steps.

```json
{
  "id": "evt_008",
  "event": "steps",
  "data": {
    "steps": [
      {"id": "step_1", "text": "Log into GST portal", "detail": "Use your GSTIN", "fact_ids": []},
      {"id": "step_2", "text": "Pay ₹4,200", "detail": "Via net banking or UPI", "fact_ids": ["fact_1"]},
      {"id": "step_3", "text": "File response if disputed", "detail": "Within 30 days", "fact_ids": []}
    ]
  }
}
```

### `checklist`
Documents to gather.

```json
{
  "id": "evt_009",
  "event": "checklist",
  "data": {"checklist": [{"id": "chk_1", "text": "GST return for Q3"}, {"id": "chk_2", "text": "Payment receipt"}]}}
```

### `big_print`
Large-print summary lines.

```json
{
  "id": "evt_010",
  "event": "big_print",
  "data": {"lines": ["₹4,200 due", "12 Nov 2024", "Pay or respond"]}
}
```

### `warning`
Warning about analysis quality (can appear at any time, multiple).

```json
{
  "id": "evt_011",
  "event": "warning",
  "data": {
    "code": "low_confidence_date",
    "message": "Date extracted with low confidence; verify manually",
    "bbox": {"x": 0.1, "y": 0.3, "width": 0.4, "height": 0.05}
  }
}
```

Warning codes:
- `low_confidence_date` — date extraction confidence < 0.7
- `low_confidence_amount` — amount extraction confidence < 0.7
- `unreadable_region` — OCR could not read a region
- `no_deadline_found` — no deadline detected in letter
- `verifier_mismatch` — LLM output contains dates/amounts not in deterministic facts
- `clarifying_question` — engine needs one clarification from user

### `clarifying_question`
Single question with tap-chip options (at most one per letter).

```json
{
  "id": "evt_012",
  "event": "clarifying_question",
  "data": {
    "id": "cq_1",
    "text": "Is this notice for you or your company?",
    "options": ["Me personally", "My company", "Not sure"]
  }
}
```

### `done`
Full answer (all fields populated).

```json
{
  "id": "evt_013",
  "event": "done",
  "data": { ... full Answer object ... }
}
```

### `error`
Typed error.

```json
{
  "id": "evt_err",
  "event": "error",
  "data": {"code": "ocr_failed", "message": "Could not read text from image", "retryable": true}
}
```

Error codes: `unsupported_file`, `unreadable_image`, `ocr_failed`, `model_unavailable`, `timeout`, `internal`

## Connection Behavior

- **Heartbeat**: Comment line `: heartbeat` every ~15 seconds
- **Replay**: If client connects after completion, server replays full sequence ending in `done`
- **Last-Event-ID**: Supported for resume
- **Connection**: `GET /api/letters/{id}/events`

## UI Rendering Rules

1. Render `facts` immediately — show bounding boxes on the letter image
2. Show `deadline` as soon as it arrives — compute relative time client-side
3. `verdict` + `severity` = primary answer card header
4. `explanation` / `steps` / `checklist` / `big_print` can render in any order as they arrive
5. `warning` with `bbox` -> highlight that region on the letter
6. `clarifying_question` -> show as inline chips, pause other rendering until answered
6. `done` -> final state, enable all actions (reminder, reply, etc.)
7. `error` -> show error state with retry button if `retryable: true`