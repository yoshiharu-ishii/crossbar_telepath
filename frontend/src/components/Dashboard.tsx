import { useEffect, useState } from "react";
import type { CallMeta } from "../types";
import { angerColor, clock, day, shortId } from "../anger";

/** 通話時間(秒)。通話中は現在時刻までの経過。 */
function durationSec(c: CallMeta, nowSec: number): number | null {
  if (!c.started_at) return null;
  const end = c.live ? nowSec : c.ended_at;
  if (!end || end < c.started_at) return null;
  return end - c.started_at;
}

function fmtDur(sec: number | null): string {
  if (sec == null) return "—";
  const s = Math.floor(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`
    : `${m}:${String(r).padStart(2, "0")}`;
}

/** 会話一覧(SVビュー)。全呼を明細テーブルで一覧する。
    通話中を上に**怒り順**で置く——荒れている呼を探す作業を人に残さない。 */
export function Dashboard(props: {
  calls: CallMeta[];
  myEmail?: string;
  onOpen: (id: string) => void;
  onClaim: (id: string) => void;
}) {
  // 通話中の経過時間と累計を動かすための時計(ライブ呼があるときだけ刻む)
  const [nowSec, setNowSec] = useState(() => Date.now() / 1000);
  const hasLive = props.calls.some((c) => c.live);
  useEffect(() => {
    if (!hasLive) return;
    const t = setInterval(() => setNowSec(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [hasLive]);

  const rows = [
    ...props.calls
      .filter((c) => c.live)
      .sort((a, b) => (b.anger_now ?? b.max_anger ?? 0) - (a.anger_now ?? a.max_anger ?? 0)),
    ...props.calls
      .filter((c) => !c.live)
      .sort((a, b) => (b.started_at || 0) - (a.started_at || 0)),
  ];

  const totalSec = rows.reduce((acc, c) => acc + (durationSec(c, nowSec) ?? 0), 0);

  return (
    <div className="feed px-4 py-3">
      <div className="text-secondary small fw-semibold mb-2">
        会話一覧 — 通話中 {rows.filter((c) => c.live).length} / 全 {rows.length} 件
        <span className="ms-3">累計通話時間 <span className="font-monospace">{fmtDur(totalSec)}</span></span>
      </div>
      <table className="table table-hover align-middle bg-body rounded overflow-hidden shadow-sm mb-0">
        <thead>
          <tr className="small text-secondary">
            <th style={{ width: 44 }}>No</th>
            <th style={{ width: 110 }}>Call ID</th>
            <th style={{ width: 76 }}>状態</th>
            <th style={{ width: 120 }}>担当</th>
            <th style={{ width: 64 }}>日付</th>
            <th style={{ width: 78 }}>開始</th>
            <th style={{ width: 78 }}>終了</th>
            <th style={{ width: 70 }}>時間</th>
            <th style={{ width: 150 }}>怒り</th>
            <th style={{ width: 84 }}>カスハラ</th>
            <th>一言概要</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={11} className="text-center text-secondary small py-4">
                まだ呼がありません。
              </td>
            </tr>
          )}
          {rows.map((c, i) => (
            <Row key={c.contact_id} c={c} no={i + 1} nowSec={nowSec} {...props} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Row({ c, no, nowSec, myEmail, onOpen, onClaim }: {
  c: CallMeta;
  no: number;
  nowSec: number;
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
            className="btn btn-sm btn-outline-primary py-0 text-nowrap"
            style={{ fontSize: 12 }}
            onClick={() => onClaim(c.contact_id)}
          >
            取る
          </button>
        ) : (
          <span className="text-secondary small">—</span>
        )}
      </td>
      <td className="small font-monospace text-secondary">{day(c.started_at)}</td>
      <td className="small font-monospace">{clock(c.started_at)}</td>
      <td className="small font-monospace">
        {c.live ? <span className="text-success">—</span> : clock(c.ended_at)}
      </td>
      <td className={`small font-monospace ${c.live ? "text-success" : ""}`}>
        {fmtDur(durationSec(c, nowSec))}
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
