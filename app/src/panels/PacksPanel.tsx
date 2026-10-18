import { useEffect, useState } from "react";
import { fetchPacks } from "../lib/api";
import type { Pack } from "../lib/types";

export function PacksPanel() {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPacks()
      .then((r) => setPacks(r.packs))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div>
      <h2 className="rb-section-title">Notice Packs</h2>
      <p className="rb-small" style={{ marginTop: 0, marginBottom: 16 }}>
        Country/language rule packs loaded by the engine. Each pack defines keywords,
        severity, deadline rules, and reply templates.
      </p>
      {error && <div className="rb-inverted">ERROR: {error}</div>}
      {packs.length === 0 && !error && <div className="rb-empty">NO PACKS FOUND</div>}
      <div className="rb-grid-2">
        {packs.map((p) => (
          <div key={p.path} className="rb-card">
            <div className="rb-row rb-row--between">
              <h3 className="rb-h4">{p.name}</h3>
              <span
                className={`rb-chip rb-chip--status ${
                  p.severity === "see_professional"
                    ? "rb-chip--status-error"
                    : p.severity === "act_soon"
                      ? "rb-chip--status-warning"
                      : "rb-chip--status-active"
                }`}
              >
                {p.severity}
              </span>
            </div>
            <p className="rb-mono rb-tiny" style={{ margin: "4px 0 8px" }}>
              {p.country}/{p.language} · {p.path}
            </p>
            <p className="rb-small">{p.meaning}</p>
            <div className="rb-chip-row" style={{ marginTop: 8 }}>
              {p.keywords.slice(0, 8).map((k) => (
                <span key={k} className="rb-chip">
                  {k}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
