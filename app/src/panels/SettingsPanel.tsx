import { useEffect, useState } from "react";
import DecryptedText from "../bits/DecryptedText";
import { fetchHealth, getApiBase, setApiBase } from "../lib/api";
import type { HealthResponse } from "../lib/types";

export function SettingsPanel({ onHealthChange }: { onHealthChange: () => void }) {
  const [base, setBase] = useState(getApiBase());
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [saved, setSaved] = useState(false);

  const probe = async () => {
    try {
      setHealth(await fetchHealth());
    } catch {
      setHealth(null);
    }
  };

  useEffect(() => {
    void probe();
  }, []);

  const save = () => {
    setApiBase(base);
    setSaved(true);
    onHealthChange();
    void probe();
    setTimeout(() => setSaved(false), 1500);
  };

  return (
    <div style={{ maxWidth: 640 }}>
      <h2 className="rb-section-title">Settings</h2>

      <div className="rb-card" style={{ marginBottom: 24 }}>
        <label className="rb-label" htmlFor="api-base">
          API Base URL
        </label>
        <input
          id="api-base"
          className="rb-input"
          value={base}
          onChange={(e) => setBase(e.target.value)}
          placeholder="http://127.0.0.1:8000"
        />
        <p className="rb-helper">
          Local-only. The engine never phones home. Default: http://127.0.0.1:8000
        </p>
        <div className="rb-row" style={{ marginTop: 12 }}>
          <button type="button" className="rb-btn rb-btn--md" onClick={save}>
            {saved ? "Saved ✓" : "Save"}
          </button>
          <button
            type="button"
            className="rb-btn rb-btn--secondary rb-btn--md"
            onClick={() => void probe()}
          >
            Test Connection
          </button>
        </div>
      </div>

      <div className="rb-card rb-card--elevated">
        <span className="rb-label">Engine Status</span>
        {!health ? (
          <p className="rb-mono">
            <DecryptedText text="UNREACHABLE" animateOn="view" effect="scramble" />
          </p>
        ) : (
          <div className="rb-stack">
            <div className="rb-row">
              <span
                className={`rb-chip rb-chip--status ${
                  health.status === "ok" ? "rb-chip--status-active" : "rb-chip--status-warning"
                }`}
              >
                {health.status.toUpperCase()}
              </span>
              <span className="rb-chip rb-chip--status rb-chip--status-default">
                ENGINE {health.engine_mode.toUpperCase()}
              </span>
              <span className="rb-chip rb-chip--status rb-chip--status-default">
                v{health.version}
              </span>
            </div>
            <p className="rb-mono rb-small">
              ollama: {health.ollama_connected ? "CONNECTED" : "NOT CONNECTED"}
              <br />
              model: {health.model_available ? "AVAILABLE" : "NOT AVAILABLE"}
              <br />
              offline: {health.offline ? "YES" : "NO"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
