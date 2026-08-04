// バックエンドのWS/RESTが返す形。スキーマの正は backend/hub.py の meta()/as_dict()

export interface Message {
  speaker: "customer" | "agent";
  item_id?: string;
  text?: string;
  delta?: string;
  final?: boolean;
  ts?: number;
  anger_score?: number | null;
  anger_reason?: string | null;
  voice_score?: number | null;
  voice_tone?: string | null;
  audio_start_ms?: number | null;
  audio_end_ms?: number | null;
}

export interface CallCard {
  summary: string;
  topic: string;
  next_action: string;
  callback_needed: boolean;
  callback_reason: string;
  unresolved: string[];
  harassment: boolean;
  harassment_quote: string;
}

export interface CallMeta {
  contact_id: string;
  label?: string;
  customer_number?: string | null;
  started_at?: number;
  ended_at?: number | null;
  message_count?: number;
  max_anger?: number | null;
  max_voice_anger?: number | null;
  summary?: string | null;
  card?: CallCard | null;
  has_recording?: boolean;
  live?: boolean;
  owner_email?: string | null;
  // ここから下はクライアント側の付加情報(WSイベントから育てる)。
  // 監視卓が「選択していない呼」の今を知るために持つ
  anger_now?: number | null;
  reason_now?: string | null;
}

export interface CallRecord extends CallMeta {
  messages: Message[];
}

export interface RecordingFile {
  file: string;
  size: number;
}

// WSで流れてくるイベント(typeで判別)
export type WsEvent =
  | ({ type: "call_started" } & CallMeta)
  | ({ type: "call_ended" } & CallMeta)
  | ({ type: "transcript"; contact_id: string } & Message)
  | { type: "emotion"; contact_id: string; item_id?: string; score: number; reason?: string; alert?: boolean }
  | { type: "voice"; contact_id: string; item_id?: string; score: number; tone?: string }
  | { type: "error"; contact_id: string; speaker?: string; message: string }
  | { type: "call_updated"; contact_id: string; owner_email?: string | null };
// 注意: サーバーはこの型に無いイベントも流す(例: "speech")。型を緩めると
// 判別unionが壊れるので、未知typeはreducerのdefault節で受ける(実行時の保険)
