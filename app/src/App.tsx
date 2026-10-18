import { useCallback, useEffect, useState } from "react";
import { Sidebar, type PanelId } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { DecodePanel } from "./panels/DecodePanel";
import { HistoryPanel } from "./panels/HistoryPanel";
import { PacksPanel } from "./panels/PacksPanel";
import { SettingsPanel } from "./panels/SettingsPanel";
import { fetchHealth } from "./lib/api";
import type { HealthResponse } from "./lib/types";

const TITLES: Record<PanelId, string> = {
  decode: "Decode",
  history: "History",
  packs: "Notice Packs",
  settings: "Settings",
};

export default function App() {
  const [panel, setPanel] = useState<PanelId>("decode");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const probeHealth = useCallback(async () => {
    try {
      setHealth(await fetchHealth());
      setHealthError(null);
    } catch (e) {
      setHealth(null);
      setHealthError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void probeHealth();
  }, [probeHealth]);

  return (
    <div className="rb-app">
      <Sidebar
        active={panel}
        onSelect={setPanel}
        version={health?.version ?? "0.1.0"}
      />
      <div className="rb-main">
        <TopBar title={TITLES[panel]} health={health} healthError={healthError} />
        <main className="rb-content">
          {panel === "decode" && <DecodePanel />}
          {panel === "history" && <HistoryPanel onOpenDecode={() => setPanel("decode")} />}
          {panel === "packs" && <PacksPanel />}
          {panel === "settings" && <SettingsPanel onHealthChange={() => void probeHealth()} />}
        </main>
      </div>
    </div>
  );
}
