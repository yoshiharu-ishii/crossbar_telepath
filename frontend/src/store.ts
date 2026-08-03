// 画面の状態と、WSイベント/操作をそれに畳み込むreducer。
//
// 旧実装(素のJS)では手動でDOMと状態を同期しており、「通話終了でヘッダを
// 再描画したら状況パネルが消える」類のバグを2回踏んだ。状態を1箇所に集めて
// 描画を宣言的にするのがSPA化の主目的で、このファイルがその「1箇所」。

import type { CallMeta, CallRecord, Message, WsEvent } from "./types";

export interface Situation {
  score: number | null;          // テキスト判定(最新の発話)
  reason: string;
  voice: { score: number; tone: string; itemId?: string } | null;
  lastItemId?: string;           // 最新のテキスト判定が付いた発話
  maxAnger: number | null;       // 融合値(テキスト/声の高い方)の最大
}

/** 表示用の融合値。**同じ発話に付いた声だけ**を混ぜる(高い方を採る)。
    古い発話の声を混ぜ続けると、相手が落ち着いてもゲージが下がらなくなる。
    maxにするのは、実測で声がテキストを先行する(早期検知が目的)ため */
export function fusedScore(s: Situation): number | null {
  if (s.voice && s.voice.itemId != null && s.voice.itemId === s.lastItemId) {
    return Math.max(s.score ?? 0, s.voice.score);
  }
  return s.score;
}

export interface State {
  calls: Map<string, CallMeta>;
  mode: "live" | "history";
  selectedId: string | null;
  messages: Message[]; // 表示中の呼の発話
  situation: Situation;
  alert: { score: number; reason: string } | null;
  wsStatus: string;
}

export const initialState: State = {
  calls: new Map(),
  mode: "live",
  selectedId: null,
  messages: [],
  situation: { score: null, reason: "", voice: null, maxAnger: null },
  alert: null,
  wsStatus: "接続中…",
};

export type Action =
  | { type: "ws_status"; status: string }
  | { type: "history_loaded"; metas: CallMeta[] }
  | { type: "open_call"; record: CallRecord; mode: State["mode"] }
  | { type: "go_live" }
  | { type: "ws_event"; ev: WsEvent };

function upsert(calls: Map<string, CallMeta>, meta: CallMeta): Map<string, CallMeta> {
  const next = new Map(calls);
  next.set(meta.contact_id, { ...next.get(meta.contact_id), ...meta });
  return next;
}

/** 保存済みの発話からパネル状態を復元する(最後に判定が付いた発話が「今」) */
function situationFrom(messages: Message[], meta: CallMeta): Situation {
  let score: number | null = null;
  let reason = "";
  let voice: Situation["voice"] = null;
  let lastItemId: string | undefined;
  let maxAnger: number | null = meta.max_anger ?? null;
  for (const m of messages) {
    if (m.anger_score != null) {
      score = m.anger_score;
      reason = m.anger_reason || "";
      lastItemId = m.item_id;
    }
    if (m.voice_score != null)
      voice = { score: m.voice_score, tone: m.voice_tone || "", itemId: m.item_id };
    const fused = Math.max(m.anger_score ?? 0, m.voice_score ?? 0);
    if (m.anger_score != null || m.voice_score != null)
      if (maxAnger == null || fused > maxAnger) maxAnger = fused;
  }
  return { score, reason, voice, lastItemId, maxAnger };
}

export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "ws_status":
      return { ...state, wsStatus: action.status };

    case "history_loaded": {
      let calls = state.calls;
      for (const m of action.metas) calls = upsert(calls, m);
      return { ...state, calls };
    }

    case "open_call": {
      const { record, mode } = action;
      const { messages, ...meta } = record;
      return {
        ...state,
        mode,
        selectedId: record.contact_id,
        calls: upsert(state.calls, meta),
        messages: messages ?? [],
        situation: situationFrom(messages ?? [], meta),
        alert: null,
      };
    }

    case "go_live":
      return { ...state, mode: "live", selectedId: null, messages: [],
               situation: { score: null, reason: "", voice: null, maxAnger: null }, alert: null };

    case "ws_event":
      return applyWs(state, action.ev);
    default:
      return state;
  }
}

function applyWs(state: State, ev: WsEvent): State {
  switch (ev.type) {
    case "call_started": {
      const calls = upsert(state.calls, ev);
      // liveモードなら新しい呼を追いかける(発話は空から)
      if (state.mode === "live") {
        return { ...state, calls, selectedId: ev.contact_id, messages: [],
                 situation: { score: null, reason: "", voice: null, maxAnger: null }, alert: null };
      }
      return { ...state, calls };
    }

    case "call_ended": {
      // ヘッダは呼のメタから再描画されるが、状況パネルの状態(situation)は
      // ここでは触らない。終了直後こそ読みたい情報なので消してはいけない
      return { ...state, calls: upsert(state.calls, ev) };
    }

    case "transcript": {
      const { type: _, contact_id, ...msg } = ev;
      let calls = state.calls;
      const meta = calls.get(contact_id);
      if (meta && msg.final) {
        calls = upsert(calls, { contact_id, message_count: (meta.message_count ?? 0) + 1 });
      }
      if (contact_id !== state.selectedId) return { ...state, calls };
      const key = `${msg.speaker}:${msg.item_id}`;
      const idx = state.messages.findIndex((m) => `${m.speaker}:${m.item_id}` === key);
      const messages = [...state.messages];
      if (idx < 0) {
        messages.push({ ...msg, text: msg.final ? msg.text : msg.delta || "" });
      } else if (msg.final) {
        messages[idx] = { ...messages[idx], ...msg };
      } else {
        messages[idx] = { ...messages[idx], text: (messages[idx].text || "") + (msg.delta || "") };
      }
      return { ...state, calls, messages };
    }

    case "emotion": {
      if (ev.contact_id !== state.selectedId) return state;
      const messages = state.messages.map((m) =>
        m.item_id === ev.item_id && m.speaker === "customer"
          ? { ...m, anger_score: ev.score, anger_reason: ev.reason }
          : m,
      );
      const maxAnger =
        state.situation.maxAnger == null || ev.score > state.situation.maxAnger
          ? ev.score
          : state.situation.maxAnger;
      const calls =
        state.selectedId != null
          ? upsert(state.calls, { contact_id: state.selectedId, max_anger: maxAnger })
          : state.calls;
      return {
        ...state,
        calls,
        messages,
        situation: { ...state.situation, score: ev.score, reason: ev.reason || "",
                     lastItemId: ev.item_id, maxAnger },
        alert: ev.alert ? { score: ev.score, reason: ev.reason || "" } : state.alert,
      };
    }

    case "voice": {
      if (ev.contact_id !== state.selectedId) return state;
      const messages = state.messages.map((m) =>
        m.item_id === ev.item_id && m.speaker === "customer"
          ? { ...m, voice_score: ev.score, voice_tone: ev.tone }
          : m,
      );
      const maxAnger =
        state.situation.maxAnger == null || ev.score > state.situation.maxAnger
          ? ev.score
          : state.situation.maxAnger;
      const alert = (ev as { alert?: boolean }).alert
        ? { score: ev.score, reason: `声のトーン: ${ev.tone || ""}` }
        : state.alert;
      const calls =
        state.selectedId != null
          ? upsert(state.calls, { contact_id: state.selectedId, max_anger: maxAnger })
          : state.calls;
      return {
        ...state,
        calls,
        messages,
        situation: { ...state.situation, maxAnger,
                     voice: { score: ev.score, tone: ev.tone || "", itemId: ev.item_id } },
        alert,
      };
    }

    case "error":
      return state; // 表示は今のところフィード側でやらない(ログはサーバーに残る)

    default:
      // WSは型定義に無いイベントも流してくる(例: "speech" = 発話中の合図)。
      // ここでundefinedを返すと状態が丸ごと壊れる——SPA化直後に実際に踏んだ。
      // TypeScriptの網羅チェックは実行時のペイロードまでは守らない
      return state;
  }
}
