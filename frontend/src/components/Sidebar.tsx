import type { State } from "../store";
import type { RecordingFile } from "../types";
import { clock, day, shortId } from "../anger";

export function Sidebar(props: {
  state: State;
  files: RecordingFile[];
  onSelect: (id: string) => void;
  onGoLive: () => void;
  onReplay: (file: string) => void;
}) {
  const { state, files } = props;
  const metas = [...state.calls.values()].sort(
    (a, b) => (b.started_at || 0) - (a.started_at || 0),
  );
  const active = metas.find((c) => c.live);

  return (
    <aside className="sidebar border-end bg-body">
      <div className="text-secondary small px-3 pt-2">ライブ</div>
      <div
        className={`call-item px-3 py-2 border-bottom ${state.mode === "live" ? "bg-primary-subtle" : ""}`}
        onClick={props.onGoLive}
        data-testid="live-item"
      >
        <div className="d-flex align-items-center gap-2">
          <span className={`dot ${active ? "live" : ""}`} />
          <span className="fw-semibold small">リアルタイム</span>
        </div>
        <div className="text-secondary" style={{ fontSize: 11 }}>
          {active ? `通話中 · ${shortId(active.contact_id)}` : "待機中 · 呼が来ると自動表示"}
        </div>
      </div>

      <div className="text-secondary small px-3 pt-2">呼の履歴</div>
      {metas.length === 0 && (
        <div className="text-secondary small p-3">まだ呼がありません。</div>
      )}
      {metas.map((m) => (
        <div
          key={m.contact_id}
          className={`call-item px-3 py-2 border-bottom ${
            state.mode === "history" && m.contact_id === state.selectedId ? "bg-primary-subtle" : ""
          }`}
          onClick={() => props.onSelect(m.contact_id)}
          data-testid={`call-${m.contact_id}`}
        >
          <div className="d-flex align-items-center gap-2">
            <span className={`dot ${m.live ? "live" : ""}`} />
            <span className="fw-semibold small text-truncate">{shortId(m.contact_id)}</span>
            {m.max_anger != null && (
              <span className="badge rounded-pill text-danger border border-danger bg-danger-subtle">
                怒り {m.max_anger}
              </span>
            )}
          </div>
          <div className="text-secondary font-monospace" style={{ fontSize: 11 }}>
            {[
              `${day(m.started_at)} ${clock(m.started_at)}`,
              m.live ? "通話中" : `${m.message_count ?? 0}件`,
              m.customer_number || (m.label?.startsWith("replay:") ? m.label : null),
              m.has_recording ? "録音あり" : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>
      ))}

      <div className="text-secondary small px-3 pt-2">録音ファイル(開発用リプレイ)</div>
      {files.map((f) => (
        <div
          key={f.file}
          className="call-item px-3 py-2 border-bottom"
          onClick={() => props.onReplay(f.file)}
        >
          <div className="fw-semibold small">{f.file}</div>
          <div className="text-secondary" style={{ fontSize: 11 }}>
            {Math.round(f.size / 1024)} KB · クリックでリプレイ
          </div>
        </div>
      ))}
    </aside>
  );
}
