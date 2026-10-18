export type PanelId = "decode" | "history" | "packs" | "settings";

const NAV: { id: PanelId; label: string }[] = [
  { id: "decode", label: "Decode" },
  { id: "history", label: "History" },
  { id: "packs", label: "Packs" },
  { id: "settings", label: "Settings" },
];

interface Props {
  active: PanelId;
  onSelect: (id: PanelId) => void;
  version: string;
}

export function Sidebar({ active, onSelect, version }: Props) {
  return (
    <aside className="rb-sidebar">
      <div className="rb-sidebar__brand">
        <p className="rb-sidebar__brand-name">
          Letter
          <br />
          Decoder
        </p>
        <div className="rb-sidebar__brand-sub">LOCAL-FIRST // v{version}</div>
      </div>
      <nav className="rb-sidebar__nav">
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`rb-nav-item${active === item.id ? " rb-nav-item--active" : ""}`}
            onClick={() => onSelect(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div className="rb-sidebar__footer">
        NO CLOUD.
        <br />
        NO TRACKING.
        <br />
        YOUR LETTERS STAY LOCAL.
      </div>
    </aside>
  );
}
