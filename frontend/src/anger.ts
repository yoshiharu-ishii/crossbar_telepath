// 怒り度の段階。閾値(既定70)以上が「明確な怒り」。
// バックエンドの ANGER_THRESHOLD と対応する(表示のための写し)

export const ANGER_ALERT = 70;

export function angerClass(score: number | null | undefined): "" | "a1" | "a2" | "a3" {
  if (score == null) return "";
  if (score >= ANGER_ALERT) return "a3";
  if (score >= 45) return "a2";
  if (score >= 31) return "a1";
  return "";
}

export function angerColor(s: number): string {
  return s >= ANGER_ALERT ? "#e2564a" : s >= 45 ? "#ef9a72" : s >= 31 ? "#d8a13c" : "#2e9e5b";
}

export function clock(ts?: number | null): string {
  return ts ? new Date(ts * 1000).toLocaleTimeString("ja-JP", { hour12: false }) : "";
}

export function day(ts?: number | null): string {
  return ts
    ? new Date(ts * 1000).toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit" })
    : "";
}

export function shortId(id?: string): string {
  return id && id.length > 12 ? `${id.slice(0, 8)}…` : id || "";
}
