// 監視卓(SVビュー)の振る舞い: 怒り順・担当(挙手)・選択外の呼のライブ更新。

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";

declare const FakeWebSocket: { push(ev: unknown): void };

const CALLS = [
  { contact_id: "calm-1", live: true, started_at: 1700000100, message_count: 3,
    anger_now: 10, reason_now: "平静な問い合わせ" },
  { contact_id: "hot-1", live: true, started_at: 1700000000, message_count: 8,
    anger_now: 80, reason_now: "責任者を要求している" },
  { contact_id: "old-1", live: false, started_at: 1699990000, max_anger: 75,
    summary: "揉めた通話", ended_at: 1699990300 },
];

function mockApi(extra: Record<string, unknown> = {}) {
  const table: Record<string, unknown> = {
    "/api/recording-files": [],
    "/api/history": CALLS,
    ...extra,
  };
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    calls.push(`${init?.method || "GET"} ${path}`);
    const hit = Object.keys(table)
      .filter((k) => path.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    return { ok: hit != null, json: async () => (hit != null ? table[hit] : {}) };
  }));
  return calls;
}

beforeEach(() => vi.unstubAllGlobals());

describe("開発ツールの表示制御", () => {
  it("本番相当(devTools=false)では録音ファイルメニューが隠れる", async () => {
    mockApi();
    render(<App devTools={false} />);
    await screen.findByTestId("menu-dashboard");
    expect(screen.queryByTestId("menu-files")).not.toBeInTheDocument();
  });
  it("開発時(devTools=true)は録音ファイルメニューが出る", async () => {
    mockApi();
    render(<App devTools={true} />);
    expect(await screen.findByTestId("menu-files")).toBeInTheDocument();
  });
});

describe("監視卓", () => {
  it("既定画面が監視卓で、通話中は怒り順に並ぶ", async () => {
    mockApi();
    render(<App />);
    const rows = await screen.findAllByTestId(/^call-/);
    // 通話中(怒り順): hot-1(80) → calm-1(10)、その下に終了した呼
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "call-hot-1", "call-calm-1", "call-old-1",
    ]);
    expect(screen.getByText("責任者を要求している")).toBeInTheDocument();
  });

  it("「取る」で担当が付き、call_updatedで全画面に反映される", async () => {
    const requests = mockApi({ "/api/calls/hot-1/claim": { owner_email: "sv@example.com" } });
    render(<App />);
    await screen.findByTestId("call-hot-1");
    await userEvent.click(screen.getAllByRole("button", { name: "取る" })[0]);
    expect(requests).toContain("POST /api/calls/hot-1/claim");

    act(() => {
      FakeWebSocket.push({ type: "call_updated", contact_id: "hot-1", owner_email: "op@example.com" });
    });
    expect(await screen.findByTitle("op@example.com")).toBeInTheDocument();
  });

  it("選択していない呼のemotionも監視卓のゲージに反映される", async () => {
    mockApi();
    render(<App />);
    await screen.findByTestId("call-calm-1");
    act(() => {
      FakeWebSocket.push({ type: "emotion", contact_id: "calm-1", item_id: "x",
        score: 90, reason: "急激に激昂", alert: true });
    });
    // 90に上がったので並びも先頭に入れ替わる
    const rows = screen.getAllByTestId(/^call-/);
    expect(rows[0].getAttribute("data-testid")).toBe("call-calm-1");
    expect(rows[0].textContent).toContain("90");
    expect(rows[0].textContent).toContain("急激に激昂");
  });

  it("行クリックで詳細へ、「← 監視卓へ」で戻る", async () => {
    mockApi({ "/api/history/old-1": { ...CALLS[2], messages: [] } });
    render(<App />);
    await userEvent.click(await screen.findByTestId("call-old-1"));
    expect(await screen.findByText("← 監視卓へ")).toBeInTheDocument();
    await userEvent.click(screen.getByText("← 監視卓へ"));
    expect(await screen.findByTestId("call-hot-1")).toBeInTheDocument();
  });
});
