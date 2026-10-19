"""FastAPI application for Letter Decoder."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from contract.models import (
    Answer,
    AnswerStatus,
    DraftReplies,
    HealthResponse,
    SSEEvent,
    Tone,
)
from engine.pipeline import LetterDecoderPipeline

# Global pipeline instance
pipeline: LetterDecoderPipeline | None = None
letter_store: dict[str, Answer] = {}
letter_samples: dict[str, str] = {}
letter_queues: dict[str, asyncio.Queue] = {}
letter_logs: dict[str, list[dict]] = {}

SSE_DONE_EVENTS = ("done", "error")


def _sse_format(event: dict) -> str:
    payload = json.dumps(event["data"], default=str)
    return f"id: {event['id']}\nevent: {event['event']}\ndata: {payload}\n\n"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan."""
    global pipeline
    engine_mode = os.getenv("ENGINE_MODE", "real")
    ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    model_name = os.getenv("MODEL_NAME", "qwen2.5:7b")
    notices_dir = Path(os.getenv("NOTICES_DIR", "notices"))
    templates_dir = Path(os.getenv("TEMPLATES_DIR", "templates"))

    pipeline = LetterDecoderPipeline(
        engine_mode=engine_mode,
        ollama_host=ollama_host,
        model_name=model_name,
        notices_dir=notices_dir,
        templates_dir=templates_dir,
    )
    yield


app = FastAPI(
    title="Letter Decoder API",
    description="Local-first letter explanation engine",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - localhost by default; set CORS_ORIGINS (comma-separated) in production
_allowed_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve Dev UI at root (path resolved relative to repo root, cwd-independent)
DEV_UI_DIR = Path(__file__).resolve().parent.parent / "dev-ui"


@app.get("/")
async def root():
    return FileResponse(DEV_UI_DIR / "index.html")


# Mount dev UI
app.mount("/dev-ui", StaticFiles(directory=DEV_UI_DIR, html=True), name="dev-ui")


class LetterUploadResponse(BaseModel):
    id: str
    status: str = "queued"


class StepUpdate(BaseModel):
    done: bool


class DraftRequest(BaseModel):
    tone: Tone = Tone.NEUTRAL


# Health check
@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    ollama_connected = False
    model_available = False
    engine_mode = "unknown"

    if pipeline:
        engine_mode = pipeline.engine_mode
        if pipeline.engine_mode == "real":
            try:
                import ollama

                client = ollama.Client(host=pipeline.ollama_host)
                models = client.list()
                model_names = [m.model for m in models.get("models", [])]
                ollama_connected = True
                model_available = pipeline.model_name in model_names
            except Exception:
                pass

    is_healthy = engine_mode == "mock" or (ollama_connected and model_available)

    return HealthResponse(
        status="ok" if is_healthy else "degraded",
        engine_mode=engine_mode,
        model_available=model_available,
        ollama_connected=ollama_connected,
        offline=True,
        version="0.1.0",
    )


# Upload letter
@app.post("/api/letters", response_model=LetterUploadResponse)
async def upload_letter(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    country: str = Form("XX"),
    language: str = Form("en"),
    sample: str | None = Form(None),
):
    """Upload a letter for processing."""
    if not file and not text and not sample:
        raise HTTPException(status_code=400, detail="Either file or text must be provided")

    letter_id = uuid.uuid4().hex[:12]
    letter_samples[letter_id] = sample
    letter_queues[letter_id] = asyncio.Queue()
    submitted_at = time.perf_counter()

    # Save file if provided
    file_path = None
    if file:
        upload_dir = Path("data/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / f"{letter_id}_{file.filename}"
        content = await file.read()
        file_path.write_bytes(content)

    # Create initial answer
    answer = Answer(
        id=letter_id,
        status=AnswerStatus.QUEUED,
        meta=None,
    )
    letter_store[letter_id] = answer

    # Start background processing
    asyncio.create_task(
        _process_letter(
            letter_id,
            file_path,
            text,
            country,
            language,
            queue_ms=int((time.perf_counter() - submitted_at) * 1000),
        )
    )

    return LetterUploadResponse(id=letter_id)


async def _process_letter(
    letter_id: str,
    file_path: Path | None,
    text: str | None,
    country: str,
    language: str,
    queue_ms: int = 0,
):
    """Background task: run the pipeline and publish every SSE event to the queue."""
    global pipeline
    if not pipeline:
        return

    queue = letter_queues.setdefault(letter_id, asyncio.Queue())
    sample = letter_samples.get(letter_id)
    answer = letter_store[letter_id]
    answer.status = AnswerStatus.READING

    # Mock mode streams a canned example; real mode runs the full pipeline
    if pipeline.engine_mode == "mock":
        example_name = sample or "routine"
        try:
            pipeline.load_mock_example(example_name)
        except ValueError:
            stream = None
            error_event = {
                "id": uuid.uuid4().hex[:8],
                "event": "error",
                "data": {
                    "code": "unknown_example",
                    "message": f"Mock example not found: {example_name}",
                    "retryable": False,
                },
            }
            answer.status = AnswerStatus.ERROR
            letter_logs[letter_id] = [error_event]
            await queue.put(error_event)
            return
        stream = pipeline.process_mock(example_name)
    else:
        stream = pipeline.process(file_path, text, country, language, queue_ms=queue_ms)

    events_log: list[dict] = []
    try:
        async for event in stream:
            if event["event"] == "done":
                data = dict(event["data"])
                data["id"] = letter_id
                event = {**event, "data": data}
                letter_store[letter_id] = Answer(**data)
            elif event["event"] == "error":
                letter_store[letter_id].status = AnswerStatus.ERROR
            events_log.append(event)
            await queue.put(event)
            if event["event"] in SSE_DONE_EVENTS:
                break
    except Exception as e:  # noqa: BLE001 - publish typed error to the stream
        event = {
            "id": uuid.uuid4().hex[:8],
            "event": "error",
            "data": {"code": "internal", "message": str(e), "retryable": True},
        }
        events_log.append(event)
        letter_store[letter_id].status = AnswerStatus.ERROR
        await queue.put(event)
    finally:
        letter_logs[letter_id] = events_log


# SSE events stream
@app.get("/api/letters/{letter_id}/events")
async def letter_events(letter_id: str, request: Request):
    """Server-Sent Events stream for letter processing."""
    if letter_id not in letter_store:
        raise HTTPException(status_code=404, detail="Letter not found")

    answer = letter_store[letter_id]

    async def event_generator():
        # Completed letter: replay the recorded event log (repeat connections)
        log = letter_logs.get(letter_id)
        if log is None and answer.status in (AnswerStatus.READY, AnswerStatus.ERROR):
            log = _replay_events(answer) if answer.status == AnswerStatus.READY else []
        if log is not None:
            for event in log:
                if await request.is_disconnected():
                    break
                yield _sse_format(event)
            return

        # Still processing: tail the live queue with heartbeats
        queue = letter_queues.get(letter_id)
        if queue is None:
            yield ": heartbeat\n\n"
            return
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            yield _sse_format(event)
            if event["event"] in SSE_DONE_EVENTS:
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _replay_events(answer: Answer) -> list[SSEEvent]:
    """Replay events from a completed answer."""
    events = []

    # Stage events
    stages = [
        ("preprocess", 0.1),
        ("extract_text", 0.25),
        ("extract_facts", 0.4),
        ("classify", 0.55),
        ("load_pack", 0.65),
        ("explain", 0.8),
        ("verify", 0.95),
    ]
    for stage, progress in stages:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="stage",
                data={"stage": stage, "progress": progress},
            )
        )

    # Facts
    if answer.facts:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="facts",
                data={"facts": [f.model_dump() for f in answer.facts]},
            )
        )

    # Classification
    if answer.classification:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="classification",
                data=answer.classification.model_dump(),
            )
        )

    # Deadline
    if answer.deadline:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="deadline",
                data=answer.deadline.model_dump(),
            )
        )

    # Severity
    if answer.severity:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="severity",
                data=answer.severity.model_dump(),
            )
        )

    # Verdict
    if answer.verdict:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="verdict",
                data=answer.verdict.model_dump(),
            )
        )

    # Explanation
    if answer.explanation:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="explanation",
                data=answer.explanation.model_dump(),
            )
        )

    # Steps
    if answer.steps:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="steps",
                data={"steps": [s.model_dump() for s in answer.steps]},
            )
        )

    # Checklist
    if answer.checklist:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="checklist",
                data={"checklist": [c.model_dump() for c in answer.checklist]},
            )
        )

    # Big print
    if answer.big_print:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="big_print",
                data=answer.big_print.model_dump(),
            )
        )

    # Warnings
    for warning in answer.warnings:
        events.append(
            SSEEvent(
                id=uuid.uuid4().hex[:8],
                event="warning",
                data=warning.model_dump(),
            )
        )

    # Done
    events.append(
        SSEEvent(
            id=uuid.uuid4().hex[:8],
            event="done",
            data=answer.model_dump(),
        )
    )

    return events


# Get full answer
@app.get("/api/letters/{letter_id}", response_model=Answer)
async def get_letter(letter_id: str):
    """Get full answer for a letter."""
    if letter_id not in letter_store:
        raise HTTPException(status_code=404, detail="Letter not found")
    return letter_store[letter_id]


# List letters
@app.get("/api/letters")
async def list_letters():
    """List all processed letters."""
    result = []
    for letter_id, answer in letter_store.items():
        result.append(
            {
                "id": answer.id,
                "sender": answer.classification.sender if answer.classification else "Unknown",
                "deadline": answer.deadline.iso_date if answer.deadline else None,
                "severity": answer.severity.level.value if answer.severity else "unknown",
                "status": answer.status.value,
                "created_at": answer.created_at.isoformat() if answer.created_at else None,
            }
        )
    return {"letters": result}


# List notice packs
@app.get("/api/packs")
async def list_packs():
    """List available notice packs from the notices directory."""
    packs = []
    notices_dir = pipeline.notices_dir if pipeline else Path("notices")
    if notices_dir.exists():
        import yaml

        for path in sorted(notices_dir.rglob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            packs.append(
                {
                    "id": data.get("id", path.stem),
                    "name": data.get("names", [path.stem])[0] if data.get("names") else path.stem,
                    "country": data.get("country", "XX"),
                    "language": data.get("language", "en"),
                    "severity": data.get("severity", "unknown"),
                    "meaning": data.get("meaning", ""),
                    "keywords": data.get("keywords", []),
                    "path": str(path.relative_to(notices_dir)),
                }
            )
    return {"packs": packs}


# Update step completion
@app.patch("/api/letters/{letter_id}/steps/{step_id}")
async def update_step(letter_id: str, step_id: str, update: StepUpdate):
    """Mark a step as done/undone."""
    if letter_id not in letter_store:
        raise HTTPException(status_code=404, detail="Letter not found")

    answer = letter_store[letter_id]
    for step in answer.steps:
        if step.id == step_id:
            # In a real app, persist this to database
            return {"step_id": step_id, "done": update.done}

    raise HTTPException(status_code=404, detail="Step not found")


# Generate draft reply on demand
@app.post("/api/letters/{letter_id}/draft", response_model=DraftReplies)
async def generate_draft(letter_id: str, request: DraftRequest):
    """Generate draft reply in specified tone."""
    if letter_id not in letter_store:
        raise HTTPException(status_code=404, detail="Letter not found")

    answer = letter_store[letter_id]

    if request.tone == Tone.NEUTRAL:
        if answer.draft_replies and answer.draft_replies.neutral:
            return answer.draft_replies
        # Editable acknowledgement: admits nothing, promises nothing.
        return DraftReplies(
            neutral="I acknowledge receipt of your letter. I am reviewing its "
            "contents and will respond. This is editable example wording."
        )

    # For polite/firm, would call LLM with tone-specific prompt
    # Templates never promise payment, admit liability, or invent a reply window.
    tone_text = {
        Tone.POLITE: (
            "Thank you for your letter. I am reviewing the matter and will "
            "respond once I have checked the details. This is editable "
            "example wording."
        ),
        Tone.FIRM: (
            "I do not accept the assertions in this letter without supporting "
            "evidence. Please provide full details of the claim and the basis "
            "for it. I reserve the right to respond further. This is editable "
            "example wording."
        ),
    }

    return DraftReplies(
        neutral=answer.draft_replies.neutral if answer.draft_replies else "",
        **{request.tone.value: tone_text.get(request.tone, "")},
    )


# User correction (reprocess)
@app.post("/api/letters/{letter_id}/correct")
async def correct_letter(letter_id: str, correction: dict):
    """User correction - reprocess with correction."""
    if letter_id not in letter_store:
        raise HTTPException(status_code=404, detail="Letter not found")

    # In real implementation, would reprocess with correction
    return {"status": "reprocessing", "message": "Correction received, reprocessing..."}


# Get original image
@app.get("/api/letters/{letter_id}/image")
async def get_letter_image(letter_id: str):
    """Get original uploaded image."""
    if letter_id not in letter_store:
        raise HTTPException(status_code=404, detail="Letter not found")

    # Find uploaded file
    upload_dir = Path("data/uploads")
    for file_path in upload_dir.glob(f"{letter_id}_*"):
        return FileResponse(file_path)

    raise HTTPException(status_code=404, detail="Image not found")


# Get .ics reminder
@app.get("/api/letters/{letter_id}/reminder.ics")
async def get_reminder(letter_id: str):
    """Generate .ics calendar reminder."""
    if letter_id not in letter_store:
        raise HTTPException(status_code=404, detail="Letter not found")

    answer = letter_store[letter_id]
    if not answer.deadline or not answer.deadline.iso_date:
        raise HTTPException(status_code=400, detail="No deadline available")

    from datetime import timedelta

    dt = datetime.fromisoformat(answer.deadline.iso_date)
    dt_end = dt + timedelta(hours=1)

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Letter Decoder//EN
BEGIN:VEVENT
UID:{letter_id}@letter-decoder.local
DTSTAMP:{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}
DTSTART:{dt.strftime("%Y%m%dT%H%M%S")}
DTEND:{dt_end.strftime("%Y%m%dT%H%M%S")}
SUMMARY:{answer.verdict.text if answer.verdict else "Letter Deadline"}
DESCRIPTION:Letter Decoder reminder\\n{answer.verdict.text if answer.verdict else ""}
END:VEVENT
END:VCALENDAR"""

    return StreamingResponse(
        iter([ics_content]),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="reminder_{letter_id}.ics"'},
    )


# Delete letter
@app.delete("/api/letters/{letter_id}")
async def delete_letter(letter_id: str):
    """Delete a letter and its data."""
    if letter_id not in letter_store:
        raise HTTPException(status_code=404, detail="Letter not found")

    del letter_store[letter_id]

    # Delete uploaded file
    upload_dir = Path("data/uploads")
    for file_path in upload_dir.glob(f"{letter_id}_*"):
        file_path.unlink()

    return {"status": "deleted"}


if __name__ == "__main__":
    import uvicorn

    # Bind everywhere when PORT is set (Render), loopback-only for local dev
    port = int(os.getenv("PORT", "8000"))
    host = "0.0.0.0" if os.getenv("PORT") else "127.0.0.1"
    uvicorn.run(app, host=host, port=port)
