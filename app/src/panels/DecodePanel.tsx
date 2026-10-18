import { useCallback, useEffect, useRef, useState } from "react";
import CountUp from "../bits/CountUp";
import DecryptedText from "../bits/DecryptedText";
import { fetchDraft, openLetterEvents, updateStep, uploadLetter } from "../lib/api";
import type { Answer, SSEEnvelope } from "../lib/types";

const SAMPLES = [
  "routine",
  "act_soon",
  "see_professional",
  "low_confidence_blurry",
  "no_deadline_found",
  "clarifying_question",
  "null_bbox",
  "verified_false",
];

interface LogLine {
  kind: "info" | "event" | "warn" | "error";
  text: string;
}

function confidencePct(c: number): string {
  return `${Math.round(c * 100)}%`;
}

export function DecodePanel() {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [country, setCountry] = useState("XX");
  const [language, setLanguage] = useState("en");
  const [sample, setSample] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [log, setLog] = useState<LogLine[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [doneSteps, setDoneSteps] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [showJson, setShowJson] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef(false);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const pushLog = useCallback((kind: LogLine["kind"], text: string) => {
    setLog((prev) => [...prev.slice(-200), { kind, text }]);
  }, []);

  const handleFile = (f: File | null) => {
    setFile(f);
    if (f) pushLog("info", `FILE LOADED: ${f.name} (${f.size} bytes)`);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files[0] ?? null);
  };

  const decode = async () => {
    if (!file && !text.trim() && !sample) {
      setError("Provide a file, raw text, or a sample.");
      return;
    }
    setBusy(true);
    setError(null);
    setAnswer(null);
    setLog([]);
    setProgress(0);
    setDoneSteps(new Set());
    setDrafts({});
    setShowJson(false);
    terminalRef.current = false;

    try {
      const { id } = await uploadLetter({ file, text, country, language, sample: sample ?? undefined });
      pushLog("info", `UPLOADED // LETTER ${id}`);
      const es = openLetterEvents(
        id,
        (event, data) => {
          if (event === "stage") {
            const d = data as { stage: string; progress: number };
            setProgress(Math.round(d.progress * 100));
            pushLog("event", `STAGE ${d.stage.toUpperCase()} (${Math.round(d.progress * 100)}%)`);
          } else if (event === "warning") {
            const d = data as { code: string; message: string };
            pushLog("warn", `WARNING ${d.code}: ${d.message}`);
          } else if (event === "error") {
            const d = data as { code?: string; message?: string };
            pushLog("error", `ERROR ${d.code ?? ""}: ${d.message ?? "unknown"}`);
            setError(d.message ?? "Processing failed");
            setBusy(false);
            terminalRef.current = true;
          } else if (event === "done") {
            const d = data as unknown as Answer;
            setAnswer(d);
            setProgress(100);
            pushLog("event", "DONE");
            setBusy(false);
            terminalRef.current = true;
            es.close();
          } else {
            const env: Partial<SSEEnvelope> = { event, data: data as Record<string, unknown> };
            pushLog("event", `${(event || "").toUpperCase()} RECEIVED`);
            void env;
          }
        },
        () => {
          // Server closes the stream after done/error — that's expected
          if (!terminalRef.current) {
            pushLog("error", "SSE CONNECTION CLOSED");
          }
          setBusy(false);
        },
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      pushLog("error", msg);
      setBusy(false);
    }
  };

  const toggleStep = async (stepId: string) => {
    if (!answer) return;
    const next = !doneSteps.has(stepId);
    setDoneSteps((prev) => {
      const s = new Set(prev);
      if (next) s.add(stepId);
      else s.delete(stepId);
      return s;
    });
    try {
      await updateStep(answer.id, stepId, next);
      pushLog("info", `STEP ${stepId} → ${next ? "DONE" : "UNDONE"}`);
    } catch (e) {
      pushLog("error", e instanceof Error ? e.message : String(e));
    }
  };

  const loadDraft = async (tone: "neutral" | "polite" | "firm") => {
    if (!answer) return;
    try {
      const d = await fetchDraft(answer.id, tone);
      const text = tone === "neutral" ? d.neutral : tone === "polite" ? d.polite ?? "" : d.firm ?? "";
      setDrafts((prev) => ({ ...prev, [tone]: text }));
      pushLog("info", `DRAFT ${tone.toUpperCase()} GENERATED`);
    } catch (e) {
      pushLog("error", e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="rb-decode">
      <section className="rb-decode__input">
        <h2 className="rb-section-title">Input</h2>

        <div>
          <label className="rb-label" htmlFor="ld-file">
            Letter File
          </label>
          <div
            className={`rb-dropzone${dragOver ? " rb-dropzone--over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => document.getElementById("ld-file")?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter") document.getElementById("ld-file")?.click();
            }}
          >
            {file ? file.name : "DROP IMAGE / PDF HERE OR CLICK"}
            <input
              id="ld-file"
              type="file"
              accept="image/*,.pdf"
              style={{ display: "none" }}
              onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
            />
          </div>
        </div>

        <div>
          <label className="rb-label" htmlFor="ld-text">
            Raw Text
          </label>
          <textarea
            id="ld-text"
            className="rb-textarea"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste letter text here…"
            spellCheck={false}
          />
        </div>

        <div className="rb-grid-2">
          <div>
            <label className="rb-label" htmlFor="ld-country">
              Country
            </label>
            <input
              id="ld-country"
              className="rb-input"
              value={country}
              onChange={(e) => setCountry(e.target.value.toUpperCase().slice(0, 2))}
              maxLength={2}
            />
          </div>
          <div>
            <label className="rb-label" htmlFor="ld-lang">
              Language
            </label>
            <input
              id="ld-lang"
              className="rb-input"
              value={language}
              onChange={(e) => setLanguage(e.target.value.slice(0, 5))}
              maxLength={5}
            />
          </div>
        </div>

        <div>
          <span className="rb-label">Mock Samples</span>
          <div className="rb-chip-row">
            {SAMPLES.map((s) => (
              <button
                key={s}
                type="button"
                className={`rb-chip${sample === s ? " rb-chip--active" : ""}`}
                onClick={() => setSample(sample === s ? null : s)}
              >
                {s.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </div>

        {error && <div className="rb-input rb-input--error rb-mono rb-small">{error}</div>}

        <button type="button" className="rb-btn rb-btn--lg" onClick={decode} disabled={busy}>
          {busy ? "Decoding…" : "Decode Letter"}
        </button>

        {busy && (
          <div className="rb-progress" aria-label="processing progress">
            <div className="rb-progress__fill" style={{ width: `${progress}%` }} />
          </div>
        )}

        <div>
          <span className="rb-label">Stream Log</span>
          <div className="rb-log" ref={logRef}>
            {log.length === 0
              ? "// IDLE"
              : log.map((l, i) => (
                  <div
                    key={i}
                    className={`rb-log__line--${l.kind === "info" ? "event" : l.kind}`}
                  >
                    {l.text}
                  </div>
                ))}
          </div>
        </div>
      </section>

      <section className="rb-decode__results">
        {!answer && !busy && (
          <div className="rb-empty">
            <DecryptedText
              text="AWAITING INPUT"
              animateOn="view"
              effect="scramble"
              className="rb-mono"
            />
            <p className="rb-small" style={{ marginTop: 16 }}>
              Upload a letter or pick a mock sample, then hit decode.
            </p>
          </div>
        )}

        {answer && (
          <>
            {answer.big_print && answer.big_print.lines.length > 0 && (
              <div className="rb-bigprint">
                {answer.big_print.lines.map((l, i) => (
                  <div key={i}>{l}</div>
                ))}
              </div>
            )}

            {answer.verdict && (
              <div className="rb-card rb-card--elevated">
                <div className="rb-row rb-row--between">
                  <span className="rb-label" style={{ margin: 0 }}>
                    Verdict
                  </span>
                  <span className="rb-chip rb-chip--status rb-chip--status-default">
                    {confidencePct(answer.verdict.confidence)}
                  </span>
                </div>
                <p className="rb-h4" style={{ marginTop: 8 }}>
                  {answer.verdict.text}
                </p>
              </div>
            )}

            <div className="rb-grid-2">
              {answer.severity && (
                <div className="rb-card">
                  <span className="rb-label">Severity</span>
                  <span
                    className={`rb-chip rb-chip--status ${
                      answer.severity.level === "see_professional"
                        ? "rb-chip--status-error"
                        : answer.severity.level === "act_soon"
                          ? "rb-chip--status-warning"
                          : "rb-chip--status-active"
                    }`}
                  >
                    {answer.severity.level.replace(/_/g, " ")}
                  </span>
                  <p className="rb-small" style={{ marginTop: 8 }}>
                    {answer.severity.reason}
                  </p>
                </div>
              )}
              {answer.deadline && (
                <div className="rb-card">
                  <span className="rb-label">Deadline</span>
                  <p className="rb-mono" style={{ margin: "8px 0 0" }}>
                    {answer.deadline.iso_date ?? "NONE FOUND"}
                  </p>
                  <p className="rb-tiny" style={{ color: "#444" }}>
                    kind: {answer.deadline.kind} · conf {confidencePct(answer.deadline.confidence)}
                  </p>
                </div>
              )}
            </div>

            {answer.classification && (
              <div className="rb-card">
                <span className="rb-label">Classification</span>
                <p className="rb-mono" style={{ margin: "8px 0 0" }}>
                  {answer.classification.notice_type_id} · {answer.classification.country}/
                  {answer.classification.language}
                </p>
                <p className="rb-small">
                  sender: {answer.classification.sender ?? "UNKNOWN"} · conf{" "}
                  {confidencePct(answer.classification.confidence)}
                </p>
              </div>
            )}

            <div>
              <div className="rb-row rb-row--between">
                <h3 className="rb-section-title">
                  Facts{" "}
                  <CountUp
                    to={answer.facts.length}
                    duration={0.6}
                    className="rb-mono"
                    style={{ fontSize: 14 }}
                  />
                </h3>
              </div>
              <div className="rb-card" style={{ paddingTop: 8, paddingBottom: 8 }}>
                {answer.facts.length === 0 && <p className="rb-small">NO FACTS EXTRACTED</p>}
                {answer.facts.map((f) => (
                  <div key={f.id} className="rb-fact">
                    <span className="rb-fact__kind">{f.kind}</span>
                    <span className="rb-fact__value">{f.raw_value}</span>
                    <span className="rb-fact__meta">
                      {confidencePct(f.confidence)}
                      {f.verified ? " ✓ VERIFIED" : ""}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {answer.explanation && (
              <div className="rb-card">
                <span className="rb-label">What This Means</span>
                <p className="rb-body">{answer.explanation.simple}</p>
                <p className="rb-small" style={{ marginTop: 8, color: "#333" }}>
                  {answer.explanation.detailed}
                </p>
              </div>
            )}

            {answer.steps.length > 0 && (
              <div>
                <h3 className="rb-section-title">Next Steps</h3>
                <ul className="rb-list">
                  {answer.steps.map((s) => (
                    <li key={s.id} className="rb-list-item" style={{ cursor: "default" }}>
                      <label className="rb-row" style={{ cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          className="rb-checkbox"
                          checked={doneSteps.has(s.id)}
                          onChange={() => toggleStep(s.id)}
                        />
                        <span style={{ textDecoration: doneSteps.has(s.id) ? "line-through" : "none" }}>
                          {s.text}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {answer.checklist.length > 0 && (
              <div>
                <h3 className="rb-section-title">Documents To Gather</h3>
                <div className="rb-chip-row">
                  {answer.checklist.map((c) => (
                    <span key={c.id} className="rb-chip">
                      {c.text}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {answer.clarifying_question && (
              <div className="rb-card">
                <span className="rb-label">Clarifying Question</span>
                <p className="rb-body">{answer.clarifying_question.text}</p>
                <div className="rb-chip-row" style={{ marginTop: 8 }}>
                  {answer.clarifying_question.options.map((o) => (
                    <button key={o} type="button" className="rb-chip">
                      {o}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {answer.warnings.length > 0 && (
              <div>
                <h3 className="rb-section-title">Warnings</h3>
                {answer.warnings.map((w, i) => (
                  <div key={i} className="rb-row" style={{ marginBottom: 4 }}>
                    <span className="rb-chip rb-chip--status rb-chip--status-warning">
                      {w.code}
                    </span>
                    <span className="rb-small">{w.message}</span>
                  </div>
                ))}
              </div>
            )}

            <div>
              <span className="rb-label">Draft Replies</span>
              <div className="rb-row" style={{ marginBottom: 8 }}>
                {(["neutral", "polite", "firm"] as const).map((tone) => (
                  <button
                    key={tone}
                    type="button"
                    className="rb-btn rb-btn--secondary rb-btn--sm"
                    onClick={() => loadDraft(tone)}
                  >
                    {tone}
                  </button>
                ))}
              </div>
              {Object.entries(drafts).map(([tone, d]) => (
                <div key={tone} className="rb-card" style={{ marginBottom: 8 }}>
                  <span className="rb-label">{tone}</span>
                  <p className="rb-mono rb-small">{d}</p>
                </div>
              ))}
            </div>

            <div className="rb-row">
              <button
                type="button"
                className="rb-btn rb-btn--secondary rb-btn--sm"
                onClick={() => setShowJson((v) => !v)}
              >
                {showJson ? "Hide JSON" : "Raw JSON"}
              </button>
              <a
                className="rb-btn rb-btn--ghost rb-btn--sm"
                href={`http://127.0.0.1:8000/api/letters/${answer.id}/reminder.ics`}
              >
                Download .ics Reminder
              </a>
            </div>
            {showJson && <pre className="rb-json">{JSON.stringify(answer, null, 2)}</pre>}
          </>
        )}
      </section>
    </div>
  );
}
