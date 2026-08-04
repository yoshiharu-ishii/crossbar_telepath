import { useState } from "react";
import { fusedScore, type Situation } from "../store";
import type { CallMeta } from "../types";
import { angerColor, clock, day, shortId } from "../anger";

/** 状況パネル。判定の「読み」はここ1箇所に集約する(発話には色とスコアだけ)。
    バロメータは累積ではなく「今この瞬間」——相手が落ち着けば下がる。 */
function SituationPanel({ s }: { s: Situation }) {
  // メインの数字はテキストと声の融合値(同じ発話なら高い方)。内訳は下の行に出す
  const score = fusedScore(s);
  const gap = s.voice != null && s.score != null ? s.voice.score - s.score : null;
  return (
    <div className="border rounded p-2 bg-body" style={{ width: 300, flex: "none" }} data-testid="situation">
      <div className="d-flex align-items-baseline gap-2" style={{ fontSize: 11 }}>
        <span className="text-secondary">相手の状態</span>
        <span className="text-secondary font-monospace" data-testid="sit-max">
          {s.maxAnger == null ? "" : `最大 ${s.maxAnger}`}
        </span>
        <span
          className="ms-auto fw-bold font-monospace fs-6"
          style={{ color: score == null ? undefined : angerColor(score) }}
          data-testid="sit-score"
        >
          {score == null ? "—" : score}
        </span>
      </div>
      <div className="gauge my-1">
        <div
          className="gauge-bar"
          style={{ width: `${score ?? 0}%`, background: angerColor(score ?? 0) }}
        />
      </div>
      <div style={{ fontSize: 12 }} data-testid="sit-reason">
        {s.reason || <span className="text-secondary">判定待ち</span>}
      </div>
      {s.voice && (
        <div className="border-top mt-1 pt-1" style={{ fontSize: 11 }} data-testid="sit-voice">
          <div className="d-flex align-items-baseline gap-2">
            <span className="text-secondary">声のトーン</span>
            <span className="fw-bold font-monospace" style={{ color: angerColor(s.voice.score) }}>
              {s.voice.score}
            </span>
            <span className="ms-auto fw-semibold" style={{ color: "var(--ct-customer)" }} data-testid="sit-gap">
              {gap != null && Math.abs(gap) >= 20 ? `テキストと ${gap > 0 ? "+" : ""}${gap}` : ""}
            </span>
          </div>
          <div>{s.voice.tone}</div>
        </div>
      )}
    </div>
  );
}

export function CallHeader(props: {
  meta: CallMeta;
  situation: Situation;
  dispatchStatus: (s: string) => void;
  onPlayhead: (ms: number | null) => void;
}) {
  const { meta } = props;
  const [busy, setBusy] = useState(false);
  return (
    <div className="d-flex align-items-start gap-3 px-3 py-2 border-bottom bg-body small text-secondary flex-wrap">
      <div className="d-flex flex-column gap-1" style={{ minWidth: 0 }}>
        <div className="d-flex align-items-center gap-3 flex-wrap">
          <span>{meta.live ? "🟢 通話中" : `終了 ${clock(meta.ended_at)}`}</span>
          <span>{shortId(meta.contact_id)}</span>
          {meta.customer_number && <span>{meta.customer_number}</span>}
          <span>
            開始 {day(meta.started_at)} {clock(meta.started_at)}
          </span>
        </div>
        {!meta.live && meta.has_recording && (
          <div className="d-flex align-items-center gap-2">
            <audio
              key={meta.contact_id}
              controls
              preload="none"
              src={`/api/recordings/${meta.contact_id}.wav`}
              title="左=相手 / 右=こちら"
              style={{ height: 32 }}
              onTimeUpdate={(e) => props.onPlayhead(e.currentTarget.currentTime * 1000)}
              onPlay={(e) => props.onPlayhead(e.currentTarget.currentTime * 1000)}
              onPause={() => props.onPlayhead(null)}
              onEnded={() => props.onPlayhead(null)}
            />
            <button
              className="btn btn-sm btn-outline-secondary text-nowrap flex-shrink-0"
              disabled={busy}
              title="録音から文字起こしを作り直す(履歴は増えない)"
              onClick={async () => {
                setBusy(true);
                const res = await fetch(`/api/reprocess/${meta.contact_id}?speed=2.0`, {
                  method: "POST",
                }).catch(() => null);
                if (!res?.ok) {
                  const body = res ? await res.json().catch(() => ({})) : {};
                  props.dispatchStatus(body.detail || "再文字起こしを開始できませんでした");
                  setTimeout(() => props.dispatchStatus("待機中"), 3000);
                  setBusy(false);
                }
              }}
            >
              再文字起こし
            </button>
          </div>
        )}
      </div>
      <div className="ms-auto">
        <SituationPanel s={props.situation} />
      </div>
    </div>
  );
}
