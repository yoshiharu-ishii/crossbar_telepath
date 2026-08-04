// APIアクセスの薄い層。認証が有効なときだけAuthorizationを付ける。
// 401が返ったらセッション切れとしてリロード(ログイン画面に戻る)。

import { currentToken } from "./auth";

let authEnabled = false;

export function setAuthEnabled(v: boolean): void {
  authEnabled = v;
}

export async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  if (!authEnabled) return fetch(url, init);
  const token = await currentToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(url, { ...init, headers });
  if (res.status === 401) location.reload(); // セッション切れ → ログインへ
  return res;
}

export async function wsUrl(): Promise<string> {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const base = `${proto}://${location.host}/ws`;
  if (!authEnabled) return base;
  const token = await currentToken();
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}
