// SPA版の振る舞いテスト。旧・素のJS版のjsdomテスト4本と同じ観点を保つ:
// 1. angerClassの段階  2. 保存済みの呼を開いたときの表示
// 3. ライブ更新と通話終了後の状態保持  4. カードが無い呼
// 書き直しの前後で「同じ振る舞い」であることの機械的な確認が目的。

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import App from "../src/App";
import { angerClass } from "../src/anger";
import type { CallRecord } from "../src/types";

declare const FakeWebSocket: {
  push(ev: unknown): void;
};

const RECORD: CallRecord = {
  contact_id: "t1",
  label: "test",
  customer_number: "+8190",
  started_at: 1700000000,
  ended_at: 1700000060,
  live: false,
  has_recording: false,
  max_anger: 75,
  card: {
    summary: "進捗確認の通話。",
    topic: "進捗確認",
    next_action: "責任者に引き継ぐ",
    callback_needed: true,
    callback_reason: "進捗を回答するため",
    unresolved: [],
    harassment: true,
    harassment_quote: "責任者を出せよ、今すぐ。",
  },
  messages: [
    { speaker: "agent", item_id: "a1", text: "伺っています", final: true, ts: 1700000001 },
    {
      speaker: "customer", item_id: "c1", text: "責任者を出せよ、今すぐ。",
      final: true, ts: 1700000002, anger_score: 75, anger_reason: "責任者要求",
      voice_score: 45, voice_tone: "語気は強いが怒鳴ってはいない",
    },
  ],
};

function mockFetch(routes: Record<string, unknown>) {
  const table: Record<string, unknown> = {
    "/api/recording-files": [],
    "/api/history": [],
    ...routes,
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    const hit = Object.keys(table)
      .filter((k) => path.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    return {
      ok: hit != null,
      json: async () => (hit != null ? table[hit] : {}),
    };
  }));
}

beforeEach(() => vi.unstubAllGlobals());

describe("angerClassの段階", () => {
  it("30/31/44/45/69/70の境界", () => {
    expect(angerClass(null)).toBe("");
    expect(angerClass(30)).toBe("");
    expect(angerClass(31)).toBe("a1");
    expect(angerClass(44)).toBe("a1");
    expect(angerClass(45)).toBe("a2");
    expect(angerClass(69)).toBe("a2");
    expect(angerClass(70)).toBe("a3");
    expect(angerClass(100)).toBe("a3");
  });
});

describe("保存済みの呼を開く", () => {
  it("色分け・状況パネル・声の食い違い・通話カードが出る", async () => {
    mockFetch({
      "/api/history/t1": RECORD,
      "/api/history": [{ ...RECORD, messages: undefined }],
    });
    render(<App />);
    await userEvent.click(await screen.findByTestId("call-t1"));

    // 吹き出し: customer側は a3(75)に着色、時刻行にスコア。理由の全文は出さない
    const bubble = (await screen.findByText("責任者を出せよ、今すぐ。", { selector: ".msg-text" }))
      .closest(".bubble")!;
    expect(bubble.className).toContain("a3");
    expect(bubble.textContent).toContain("75");
    expect(bubble.textContent).not.toContain("責任者要求");

    // 状況パネル: 現在値・最大値・読み
    expect(screen.getByTestId("sit-score")).toHaveTextContent("75");
    expect(screen.getByTestId("sit-max")).toHaveTextContent("最大 75");
    expect(screen.getByTestId("sit-reason")).toHaveTextContent("責任者要求");

    // 声の判定: 別枠+20点以上の食い違いを明示(45-75=-30)
    expect(screen.getByTestId("sit-voice")).toHaveTextContent("45");
    expect(screen.getByTestId("sit-gap")).toHaveTextContent("テキストと -30");

    // 通話カード: バッジ・原文引用・JSONリンク
    const card = screen.getByTestId("card");
    expect(card).toHaveTextContent("カスハラの疑い");
    expect(card).toHaveTextContent("責任者を出せよ、今すぐ。");
    expect(card.querySelector("a")).toHaveAttribute("href", "/api/history/t1/card.json");
  });
});

describe("ライブ更新", () => {
  it("発話→判定→アラート→通話終了後も状態が残る", async () => {
    mockFetch({
      "/api/history/t1": { ...RECORD, card: null, live: true, ended_at: null },
      "/api/history": [{ ...RECORD, card: null, live: true, ended_at: null, messages: undefined }],
    });
    render(<App />);
    await userEvent.click(await screen.findByTestId("call-t1"));
    await screen.findByTestId("situation");

    // 新しい発話
    act(() => {
      FakeWebSocket.push({ type: "transcript", contact_id: "t1", speaker: "customer",
        item_id: "x9", text: "新しい発話", final: true, ts: 1700000070 });
    });
    expect(await screen.findByText("新しい発話")).toBeInTheDocument();

    // 判定: パネル更新+アラート帯
    act(() => {
      FakeWebSocket.push({ type: "emotion", contact_id: "t1", item_id: "x9",
        score: 85, reason: "明確な怒り", alert: true });
    });
    expect(screen.getByTestId("sit-score")).toHaveTextContent("85");
    expect(screen.getByTestId("alert")).toHaveTextContent("85");

    // 通話終了でヘッダが再描画されても、状況パネルが「判定待ち」に戻らない
    // (素のJS時代に踏んだバグの回帰テスト)
    act(() => {
      FakeWebSocket.push({ type: "call_ended", contact_id: "t1", live: false,
        ended_at: 1700000080, max_anger: 85 });
    });
    expect(screen.getByTestId("sit-score")).toHaveTextContent("85");
    expect(screen.getByTestId("sit-reason")).toHaveTextContent("明確な怒り");

    // 別の呼のイベントは表示に影響しない
    act(() => {
      FakeWebSocket.push({ type: "emotion", contact_id: "OTHER", item_id: "z1",
        score: 10, reason: "無関係", alert: false });
    });
    expect(screen.getByTestId("sit-score")).toHaveTextContent("85");
  });
});

describe("テキストと声の融合", () => {
  it("同じ発話に声が付いたら高い方が主表示になり、声だけでもアラートが出る", async () => {
    mockFetch({
      "/api/history/t1": { ...RECORD, card: null, live: true, ended_at: null },
      "/api/history": [{ ...RECORD, card: null, live: true, ended_at: null, messages: undefined }],
    });
    render(<App />);
    await userEvent.click(await screen.findByTestId("call-t1"));
    await screen.findByTestId("situation");

    // テキスト判定45(アラートなし)→ 同じ発話に声78(アラートあり)
    act(() => {
      FakeWebSocket.push({ type: "transcript", contact_id: "t1", speaker: "customer",
        item_id: "x9", text: "いつまで待たせるんですか", final: true, ts: 1700000070 });
      FakeWebSocket.push({ type: "emotion", contact_id: "t1", item_id: "x9",
        score: 45, reason: "苛立ち", alert: false });
    });
    expect(screen.getByTestId("sit-score")).toHaveTextContent("45");

    act(() => {
      FakeWebSocket.push({ type: "voice", contact_id: "t1", item_id: "x9",
        score: 78, tone: "詰め寄る鋭い声", alert: true });
    });
    // 融合値: max(45, 78) = 78。声はテキストを先行するので待たずに警報
    expect(screen.getByTestId("sit-score")).toHaveTextContent("78");
    expect(screen.getByTestId("alert")).toHaveTextContent("78");
    expect(screen.getByTestId("alert")).toHaveTextContent("声のトーン");

    // 次の発話のテキスト判定(20)が来たら、古い声は混ぜない=下がる
    act(() => {
      FakeWebSocket.push({ type: "transcript", contact_id: "t1", speaker: "customer",
        item_id: "y1", text: "わかりました", final: true, ts: 1700000075 });
      FakeWebSocket.push({ type: "emotion", contact_id: "t1", item_id: "y1",
        score: 20, reason: "落ち着いた", alert: false });
    });
    expect(screen.getByTestId("sit-score")).toHaveTextContent("20");
  });
});

describe("未知のWSイベント", () => {
  it("型に無いイベント(speech等)が来ても状態が壊れない", async () => {
    mockFetch({
      "/api/history/t1": RECORD,
      "/api/history": [{ ...RECORD, messages: undefined }],
    });
    render(<App />);
    await userEvent.click(await screen.findByTestId("call-t1"));
    await screen.findByTestId("situation");

    // 実際に画面を白くしたイベント(SPA化直後に発生)
    act(() => {
      FakeWebSocket.push({ type: "speech", contact_id: "t1", speaker: "customer" });
      FakeWebSocket.push({ type: "totally_unknown_event" });
    });
    // 状態が生きていれば、続くイベントも処理できる
    act(() => {
      FakeWebSocket.push({ type: "emotion", contact_id: "t1", item_id: "c1",
        score: 85, reason: "生存確認", alert: false });
    });
    expect(screen.getByTestId("sit-score")).toHaveTextContent("85");
  });
});

describe("通話カード", () => {
  it("カードが無い呼では枠を出さない", async () => {
    mockFetch({
      "/api/history/t1": { ...RECORD, card: null },
      "/api/history": [{ ...RECORD, card: null, messages: undefined }],
    });
    render(<App />);
    await userEvent.click(await screen.findByTestId("call-t1"));
    await screen.findByTestId("situation");
    await waitFor(() => expect(screen.queryByTestId("card")).not.toBeInTheDocument());
  });
});
