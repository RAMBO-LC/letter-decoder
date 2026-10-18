"""FastAPI application for Letter Decoder."""

from __future__ import annotations

import os
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

# CORS - localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve Dev UI at root
@app.get("/")
async def root():
    return FileResponse("dev-ui/index.html")


# Mount dev UI
app.mount("/dev-ui", StaticFiles(directory="dev-ui", html=True), name="dev-ui")


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
                model_names = [m["name"] for m in models.get("models", [])]
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
):
    """Upload a letter for processing."""
    if not file and not text:
        raise HTTPException(status_code=400, detail="Either file or text must be provided")

    letter_id = uuid.uuid4().hex[:12]

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
    import asyncio

    asyncio.create_task(_process_letter(letter_id, file_path, text, country, language))

    return LetterUploadResponse(id=letter_id)


async def _process_letter(
    letter_id: str,
    file_path: Path | None,
    text: str | None,
    country: str,
    language: str,
):
    """Background task to process letter and update store."""
    global pipeline
    if not pipeline:
        return

    answer = letter_store[letter_id]
    answer.status = AnswerStatus.READING

    try:
        async for event in pipeline.process(file_path, text, country, language):
            # Update answer with latest data
            if event["event"] == "done":
                final_data = event["data"]
                answer = Answer(**final_data)
                letter_store[letter_id] = answer
            elif event["event"] == "error":
                answer.status = AnswerStatus.ERROR
                letter_store[letter_id] = answer
    except Exception:
        answer.status = AnswerStatus.ERROR
        letter_store[letter_id] = answer


# SSE events stream
@app.get("/api/letters/{letter_id}/events")
async def letter_events(letter_id: str, request: Request):
    """Server-Sent Events stream for letter processing."""
    if letter_id not in letter_store:
        raise HTTPException(status_code=404, detail="Letter not found")

    answer = letter_store[letter_id]

    async def event_generator():
        if pipeline and pipeline.engine_mode == "mock":
            # For mock mode, we need to know which example to use
            # This is simplified - in real use, the example would be determined by the input
            async for event in pipeline.process_mock("routine"):
                if await request.is_disconnected():
                    break
                yield f"id: {event['id']}\nevent: {event['event']}\ndata: {event['data']}\n\n"
        else:
            # For real mode, events are generated during processing
            # This is a simplified replay - in production, use a proper event bus
            if answer.status == AnswerStatus.READY:
                # Replay from stored answer
                events = _replay_events(answer)
                for event in events:
                    if await request.is_disconnected():
                        break
                    yield f"id: {event['id']}\nevent: {event['event']}\ndata: {event['data']}\n\n"
            else:
                # Still processing - send heartbeat
                yield ": heartbeat\n\n"

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
        # Generate neutral if not present
        return DraftReplies(
            neutral="Thank you for the notice. I will review and respond appropriately."
        )

    # For polite/firm, would call LLM with tone-specific prompt
    # For now, return mock
    tone_text = {
        Tone.POLITE: "I kindly acknowledge receipt of your notice. I will review the matter and respond within the given timeframe.",
        Tone.FIRM: "I have received your notice. I dispute the claims made and request a formal review. I expect a written response within 14 days.",
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

    uvicorn.run(app, host="127.0.0.1", port=8000)
