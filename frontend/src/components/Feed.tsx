import { useEffect, useRef } from "react";
import type { CallMeta, Message } from "../types";
import { angerClass, angerColor, clock } from "../anger";

const WHO = { customer: "相手 (FROM_CUSTOMER)", agent: "こちら (TO_CUSTOMER)" } as const;

// 発話区間だけを再生する。文字起こしが合っているか耳で確かめるため
let segAudio: HTMLAudioElement | null = null;
function playSegment(contactId: string, startMs: number, endMs: number) {
  segAudio?.pause();
  const q = new URLSearchParams({
    start_ms: String(Math.round(startMs)),
    end_ms: String(Math.round(endMs)),
  });
  segAudio = new Audio(`/api/recordings/${contactId}.wav?${q}`);
  void segAudio.play().catch(() => undefined);
}

function Bubble({ m, meta }: { m: Message; meta: CallMeta }) {
  const cls = m.speaker === "customer" ? angerClass(m.anger_score) : "";
  const canPlay = meta.has_recording && m.final && m.audio_start_ms != null;
  return (
    <div className={`row-msg ${m.speaker}`}>
      <div className={`bubble ${cls} ${m.final ? "" : "pending"}`}>
        <div className="who">{WHO[m.speaker] ?? m.speaker}</div>
        <div className="msg-text">{m.text}</div>
        {canPlay && (
          <button
            className="btn btn-sm btn-outline-secondary rounded-pill py-0 mt-1"
            style={{ fontSize: 11 }}
            onClick={() => playSegment(meta.contact_id, m.audio_start_ms!, m.audio_end_ms!)}
          >
            ▶ この発話を聞く ({(((m.audio_end_ms ?? 0) - (m.audio_start_ms ?? 0)) / 1000).toFixed(1)}秒)
          </button>
        )}
        {meta.has_recording && m.final && m.audio_start_ms == null && (
          // なぜ聞けないのかを画面で分かるようにする(黙って何も出さない方が不親切)
          <div className="text-secondary" style={{ fontSize: 11, opacity: 0.8 }}>
            位置情報なし — 「再文字起こし」で付きます
          </div>
        )}
        <div className="msg-time">
          {clock(m.ts)}
          {m.anger_score != null && (
            <span style={{ color: angerColor(m.anger_score) }}> · {m.anger_score}</span>
          )}
          {m.voice_score != null && (
            <span style={{ color: angerColor(m.voice_score) }}> · 声{m.voice_score}</span>
          )}
        </div>
      </div>
    </div>
  );
}

export function Feed({ messages, meta }: { messages: Message[]; meta: CallMeta }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // 新しい発話が来たら追いかける(ライブ視聴の既定動作)
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [messages]);
  return (
    <div className="feed px-3 py-2" ref={ref}>
      {messages.length === 0 ? (
        <div className="text-center text-secondary p-5">この呼にはまだ発話がありません。</div>
      ) : (
        messages.map((m) => <Bubble key={`${m.speaker}:${m.item_id}`} m={m} meta={meta} />)
      )}
    </div>
  );
}
