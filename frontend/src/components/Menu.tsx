import type { State } from "../store";

const ITEMS = [
  { view: "dashboard" as const, icon: "📟", label: "監視卓", hint: "全呼の状態一覧" },
  { view: "detail" as const, icon: "🔴", label: "リアルタイム", hint: "新しい呼を自動追従" },
  { view: "files" as const, icon: "🎞", label: "録音ファイル", hint: "開発用リプレイ" },
];

/** 左端のスリムなメニュー。呼の一覧は監視卓(メイン領域)へ移した。 */
export function Menu(props: {
  state: State;
  liveCount: number;
  onSelect: (view: "dashboard" | "files") => void;
  onGoLive: () => void;
}) {
  const { state } = props;
  const activeView = state.view === "detail" && state.mode === "live" ? "detail" : state.view;
  return (
    <nav className="menu border-end bg-body d-flex flex-column">
      {ITEMS.map((it) => (
        <button
          key={it.view}
          className={`menu-item btn text-start rounded-0 border-0 px-3 py-2 ${
            activeView === it.view ? "active" : ""
          }`}
          data-testid={`menu-${it.view}`}
          onClick={() => (it.view === "detail" ? props.onGoLive() : props.onSelect(it.view))}
        >
          <span className="me-2">{it.icon}</span>
          <span className="fw-semibold small">{it.label}</span>
          {it.view === "dashboard" && props.liveCount > 0 && (
            <span className="badge rounded-pill text-bg-danger ms-2">{props.liveCount}</span>
          )}
          <div className="text-secondary" style={{ fontSize: 11, paddingLeft: 26 }}>
            {it.hint}
          </div>
        </button>
      ))}
    </nav>
  );
}
