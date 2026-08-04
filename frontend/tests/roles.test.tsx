// ロール別の見え方: 応対者は静かな画面(カード無し・再文字起こし不可)、
// SVはアラート音。配信の絞り込み自体はサーバー側(test_authz.py)の仕事。

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const soundMock = vi.hoisted(() => ({ alertBeep: vi.fn() }));
vi.mock("../src/sound", () => soundMock);

import App from "../src/App";

declare const FakeWebSocket: { push(ev: unknown): void };

const RECORD = {
  contact_id: "t1", label: "t", started_at: 1700000000, ended_at: 1700000060,
  live: false, has_recording: true, max_anger: 75,
  card: { summary: "揉めた", topic: "x", next_action: "", callback_needed: false,
          callback_reason: "", unresolved: [], harassment: true, harassment_quote: "引用" },
  messages: [{ speaker: "customer", item_id: "c1", text: "発話", final: true, ts: 1700000001 }],
};

function mockApi() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const path = String(url);
    const table: Record<string, unknown> = {
      "recording-files": [],
      "/api/history/t1": RECORD,
      "/api/history": [{ ...RECORD, messages: undefined }],
    };
    const hit = Object.keys(table).filter((k) => path.includes(k)).sort((a, b) => b.length - a.length)[0];
    return { ok: true, json: async () => (hit ? table[hit] : {}) };
  }));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  mockApi();
});

describe("応対者ビュー", () => {
  it("通話カードと再文字起こしが出ない(静かな画面)", async () => {
    render(<App identity={{ email: "op@example.com", role: "operator" }} />);
    await userEvent.click(await screen.findByTestId("call-t1"));
    await screen.findByTestId("situation");
    await waitFor(() => {
      expect(screen.queryByTestId("card")).not.toBeInTheDocument();
      expect(screen.queryByText("再文字起こし")).not.toBeInTheDocument();
    });
  });

  it("アラートが出ても音は鳴らない", async () => {
    render(<App identity={{ email: "op@example.com", role: "operator" }} />);
    await userEvent.click(await screen.findByTestId("call-t1"));
    await screen.findByTestId("situation");
    act(() => {
      FakeWebSocket.push({ type: "emotion", contact_id: "t1", item_id: "c1",
        score: 85, reason: "怒り", alert: true });
    });
    expect(screen.getByTestId("alert")).toBeInTheDocument(); // 帯(状況情報)は出る
    expect(soundMock.alertBeep).not.toHaveBeenCalled();      // 音(通知)は鳴らない
  });
});

describe("SVビュー", () => {
  it("カード・再文字起こしが出て、アラートで音が鳴る", async () => {
    render(<App identity={{ email: "sv@example.com", role: "sv" }} />);
    await userEvent.click(await screen.findByTestId("call-t1"));
    expect(await screen.findByTestId("card")).toBeInTheDocument();
    expect(screen.getByText("再文字起こし")).toBeInTheDocument();
    act(() => {
      FakeWebSocket.push({ type: "emotion", contact_id: "t1", item_id: "c1",
        score: 85, reason: "怒り", alert: true });
    });
    expect(soundMock.alertBeep).toHaveBeenCalled();
  });
});
