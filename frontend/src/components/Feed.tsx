import { useEffect, useRef, type ReactNode } from "react";
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

function Bubble({ m, meta, active }: { m: Message; meta: CallMeta; active?: boolean }) {
  const cls = m.speaker === "customer" ? angerClass(m.anger_score) : "";
  const canPlay = meta.has_recording && m.final && m.audio_start_ms != null;
  return (
    <div className={`row-msg ${m.speaker}`} data-item={m.item_id}>
      <div className={`bubble ${cls} ${m.final ? "" : "pending"} ${active ? "playing-now" : ""}`}>
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

export function Feed({
  messages,
  meta,
  playhead,
  children,
}: {
  messages: Message[];
  meta: CallMeta;
  playhead?: number | null;
  children?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // 履歴を開いたときは先頭から読む。呼が切り替わった瞬間に一度だけ頭出しする
  useEffect(() => {
    if (!meta.live) ref.current?.scrollTo({ top: 0 });
  }, [meta.contact_id, meta.live]);
  // ライブ中だけ、新しい発話に追従して末尾へ流す
  useEffect(() => {
    if (meta.live) ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [messages, meta.live]);

  // 録音の再生中は、再生位置にある発話へ追従する(位置座標は頭出し再生と同じ)。
  // 「今どの発話が鳴っているか」を目でも追えるようにする
  const activeKey =
    playhead == null
      ? null
      : [...messages]
          .reverse()
          .find((m) => m.audio_start_ms != null && m.audio_start_ms <= playhead)
          ?.item_id ?? null;
  useEffect(() => {
    if (activeKey == null) return;
    const feed = ref.current;
    const el = feed?.querySelector<HTMLElement>(`[data-item="${activeKey}"]`);
    if (!feed || !el) return;
    // scrollIntoView(smooth)は非アクティブなタブでアニメーションが抑止されて
    // 届かないことがある。offsetTopは基準がoffsetParent依存でずれるので、
    // rectの差分から「発話をフィード中央に置く」位置を確定的に計算する
    const fr = feed.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    feed.scrollTop += er.top - fr.top - feed.clientHeight / 2 + el.clientHeight / 2;
  }, [activeKey]);

  return (
    <div className="feed px-3 py-2" ref={ref}>
      {children}
      {messages.length === 0 ? (
        <div className="text-center text-secondary p-5">この呼にはまだ発話がありません。</div>
      ) : (
        messages.map((m) => (
          <Bubble
            key={`${m.speaker}:${m.item_id}`}
            m={m}
            meta={meta}
            active={activeKey != null && m.item_id === activeKey}
          />
        ))
      )}
    </div>
  );
}
