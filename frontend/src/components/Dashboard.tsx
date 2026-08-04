import type { CallMeta } from "../types";
import { angerColor, clock, day, shortId } from "../anger";

/** 会話一覧(SVビュー)。全呼を明細テーブルで一覧する。
    通話中を上に**怒り順**で置く——荒れている呼を探す作業を人に残さない。 */
export function Dashboard(props: {
  calls: CallMeta[];
  myEmail?: string;
  onOpen: (id: string) => void;
  onClaim: (id: string) => void;
}) {
  const rows = [
    ...props.calls
      .filter((c) => c.live)
      .sort((a, b) => (b.anger_now ?? b.max_anger ?? 0) - (a.anger_now ?? a.max_anger ?? 0)),
    ...props.calls
      .filter((c) => !c.live)
      .sort((a, b) => (b.started_at || 0) - (a.started_at || 0)),
  ];

  return (
    <div className="feed px-4 py-3">
      <div className="text-secondary small fw-semibold mb-2">
        会話一覧 — 通話中 {rows.filter((c) => c.live).length} / 全 {rows.length} 件
      </div>
      <table className="table table-hover align-middle bg-body rounded overflow-hidden shadow-sm mb-0">
        <thead>
          <tr className="small text-secondary">
            <th style={{ width: 44 }}>No</th>
            <th style={{ width: 110 }}>Call ID</th>
            <th style={{ width: 76 }}>状態</th>
            <th style={{ width: 120 }}>担当</th>
            <th style={{ width: 86 }}>開始</th>
            <th style={{ width: 86 }}>終了</th>
            <th style={{ width: 150 }}>怒り</th>
            <th style={{ width: 84 }}>カスハラ</th>
            <th>一言概要</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={9} className="text-center text-secondary small py-4">
                まだ呼がありません。
              </td>
            </tr>
          )}
          {rows.map((c, i) => (
            <Row key={c.contact_id} c={c} no={i + 1} {...props} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Row({ c, no, myEmail, onOpen, onClaim }: {
  c: CallMeta;
  no: number;
  myEmail?: string;
  onOpen: (id: string) => void;
  onClaim: (id: string) => void;
}) {
  const score = c.live ? (c.anger_now ?? null) : (c.max_anger ?? null);
  const harass = c.card?.harassment;
  return (
    <tr data-testid={`call-${c.contact_id}`} onClick={() => onOpen(c.contact_id)} role="button">
      <td className="text-secondary small">{no}</td>
      <td>
        <div className="fw-semibold small font-monospace">{shortId(c.contact_id)}</div>
        <div className="text-secondary" style={{ fontSize: 11 }}>{c.message_count ?? 0}件</div>
      </td>
      <td>
        {c.live ? (
          <span className="badge rounded-pill text-bg-success">通話中</span>
        ) : (
          <span className="badge rounded-pill text-bg-secondary bg-opacity-50">終了</span>
        )}
      </td>
      <td onClick={(e) => e.stopPropagation()}>
        {c.owner_email ? (
          <span
            className={`badge rounded-pill ${c.owner_email === myEmail ? "text-bg-primary" : "text-bg-secondary"}`}
            title={c.owner_email}
          >
            {c.owner_email === myEmail ? "自分" : c.owner_email.split("@")[0]}
          </span>
        ) : c.live ? (
          <button
            className="btn btn-sm btn-outline-primary py-0"
            style={{ fontSize: 12 }}
            onClick={() => onClaim(c.contact_id)}
          >
            取る
          </button>
        ) : (
          <span className="text-secondary small">—</span>
        )}
      </td>
      <td className="small font-monospace">
        <div className="text-secondary" style={{ fontSize: 10 }}>{day(c.started_at)}</div>
        {clock(c.started_at)}
      </td>
      <td className="small font-monospace">
        {c.live ? <span className="text-success">—</span> : clock(c.ended_at)}
      </td>
      <td>
        <div className="d-flex align-items-center gap-2">
          <div className="gauge flex-grow-1">
            <div
              className="gauge-bar"
              style={{ width: `${score ?? 0}%`, background: angerColor(score ?? 0) }}
            />
          </div>
          <span
            className="fw-bold font-monospace small"
            style={{ width: 24, color: score == null ? undefined : angerColor(score) }}
          >
            {score ?? "—"}
          </span>
        </div>
      </td>
      <td>
        {harass === true ? (
          <span className="badge rounded-pill text-danger border border-danger bg-danger-subtle">疑い</span>
        ) : harass === false ? (
          <span className="text-secondary small">なし</span>
        ) : (
          <span className="text-secondary small">{c.live ? "判定中" : "—"}</span>
        )}
      </td>
      <td className="small text-secondary">
        <div className="text-truncate" style={{ maxWidth: 420 }}>
          {c.live ? c.reason_now || "" : c.summary || ""}
        </div>
      </td>
    </tr>
  );
}
