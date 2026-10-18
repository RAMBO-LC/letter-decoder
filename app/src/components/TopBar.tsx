import type { HealthResponse } from "../lib/types";

interface Props {
  title: string;
  health: HealthResponse | null;
  healthError: string | null;
}

function statusChipClass(status: string): string {
  if (status === "ok") return "rb-chip rb-chip--status rb-chip--status-active";
  if (status === "degraded") return "rb-chip rb-chip--status rb-chip--status-warning";
  return "rb-chip rb-chip--status rb-chip--status-error";
}

export function TopBar({ title, health, healthError }: Props) {
  return (
    <header className="rb-topbar">
      <h1 className="rb-topbar__title">{title}</h1>
      <div className="rb-topbar__meta">
        {healthError ? (
          <span className="rb-chip rb-chip--status rb-chip--status-error">
            API DOWN
          </span>
        ) : health ? (
          <>
            <span className={statusChipClass(health.status)}>API {health.status.toUpperCase()}</span>
            <span
              className={`rb-chip rb-chip--status ${
                health.engine_mode === "mock"
                  ? "rb-chip--status-warning"
                  : "rb-chip--status-default"
              }`}
            >
              ENGINE {health.engine_mode.toUpperCase()}
            </span>
            <span className="rb-chip rb-chip--status rb-chip--status-default">
              {health.model_available ? "MODEL OK" : "MODEL N/A"}
            </span>
          </>
        ) : (
          <span className="rb-chip rb-chip--status rb-chip--status-default">CHECKING…</span>
        )}
      </div>
    </header>
  );
}
