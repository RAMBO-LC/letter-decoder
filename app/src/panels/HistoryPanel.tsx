import { useCallback, useEffect, useState } from "react";
import { deleteLetter, fetchLetter, fetchLetters } from "../lib/api";
import type { Answer, LetterSummary } from "../lib/types";

export function HistoryPanel({ onOpenDecode }: { onOpenDecode: () => void }) {
  const [letters, setLetters] = useState<LetterSummary[]>([]);
  const [selected, setSelected] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { letters: list } = await fetchLetters();
      setLetters(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const open = async (id: string) => {
    try {
      setSelected(await fetchLetter(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteLetter(id);
      if (selected?.id === id) setSelected(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="rb-grid-2" style={{ alignItems: "start" }}>
      <div>
        <div className="rb-row rb-row--between" style={{ marginBottom: 16 }}>
          <h2 className="rb-section-title">Processed Letters ({letters.length})</h2>
          <button type="button" className="rb-btn rb-btn--secondary rb-btn--sm" onClick={() => void load()}>
            Refresh
          </button>
        </div>
        {error && <div className="rb-inverted rb-small">ERROR: {error}</div>}
        {letters.length === 0 && !error && (
          <div className="rb-empty">NO LETTERS YET</div>
        )}
        {letters.length > 0 && (
          <ul className="rb-list">
            {letters.map((l) => (
              <li key={l.id}>
                <div
                  className={`rb-list-item${selected?.id === l.id ? " rb-list-item--active" : ""}`}
                  onClick={() => void open(l.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void open(l.id);
                  }}
                >
                  <div className="rb-row rb-row--between">
                    <span className="rb-mono rb-small">{l.sender}</span>
                    <span
                      className={`rb-chip rb-chip--status ${
                        l.severity === "see_professional"
                          ? "rb-chip--status-error"
                          : l.severity === "act_soon"
                            ? "rb-chip--status-warning"
                            : "rb-chip--status-active"
                      }`}
                    >
                      {l.severity}
                    </span>
                  </div>
                  <div className="rb-tiny" style={{ opacity: 0.8 }}>
                    {l.id} · {l.deadline ?? "no deadline"} · {l.status}
                  </div>
                </div>
                <button
                  type="button"
                  className="rb-btn rb-btn--destructive rb-btn--sm"
                  style={{ width: "100%" }}
                  onClick={() => void remove(l.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h2 className="rb-section-title">Detail</h2>
        {!selected && <div className="rb-empty">SELECT A LETTER</div>}
        {selected && (
          <div className="rb-stack">
            {selected.verdict && (
              <div className="rb-card rb-card--elevated">
                <span className="rb-label">Verdict</span>
                <p className="rb-h4">{selected.verdict.text}</p>
              </div>
            )}
            {selected.explanation && (
              <div className="rb-card">
                <span className="rb-label">Explanation</span>
                <p className="rb-body">{selected.explanation.simple}</p>
              </div>
            )}
            <div className="rb-card">
              <span className="rb-label">Facts ({selected.facts.length})</span>
              {selected.facts.map((f) => (
                <div key={f.id} className="rb-fact">
                  <span className="rb-fact__kind">{f.kind}</span>
                  <span className="rb-fact__value">{f.raw_value}</span>
                  <span className="rb-fact__meta">{Math.round(f.confidence * 100)}%</span>
                </div>
              ))}
            </div>
            {selected.warnings.length > 0 && (
              <div className="rb-card">
                <span className="rb-label">Warnings</span>
                {selected.warnings.map((w, i) => (
                  <p key={i} className="rb-small">
                    <strong>{w.code}</strong> — {w.message}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}
        {letters.length === 0 && (
          <button
            type="button"
            className="rb-btn rb-btn--secondary"
            style={{ marginTop: 16 }}
            onClick={onOpenDecode}
          >
            Decode Your First Letter
          </button>
        )}
      </div>
    </div>
  );
}
