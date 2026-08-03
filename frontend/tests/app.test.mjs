// app.js の検証。jsdomで index.html を建て、fetch/WebSocketをスタブして
// 実物のスクリプトを流し込む。ビルドが無い構成なので、テストもビルド無しで回す。
//
// 検証の柱は「状態の持ち方」——状況パネルが通話終了で消えるバグ、発話の色分け、
// 通話カードの描画。ロジックを関数に切り出してのテストではなく、実DOMに対する
// 振る舞いで見る(app.jsは意図的にモジュール化していないため)。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(root, "index.html"), "utf8");
const appJs = readFileSync(join(root, "app.js"), "utf8");

// 保存済みの呼(履歴から開く形)。テキスト75/声45で食い違いがある想定
const RECORD = {
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

async function boot(routes = {}) {
  const dom = new JSDOM(html, { url: "http://localhost:8001/", runScripts: "outside-only" });
  const w = dom.window;
  const table = {
    "/api/recording-files": [],
    "/api/history": [],
    ...routes,
  };
  w.fetch = async (url) => {
    // app.jsは相対URLで呼ぶので、パスに正規化してから最長一致で照合する
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    const hit = Object.keys(table)
      .filter((k) => path.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    if (hit) return { ok: true, json: async () => table[hit] };
    return { ok: false, json: async () => ({}) };
  };
  w.WebSocket = class {
    constructor() { setTimeout(() => this.onopen?.(), 0); }
    close() {}
  };
  w.Audio = class { play() { return Promise.resolve(); } pause() {} };
  w.eval(appJs); // init() が走る
  await new Promise((r) => setTimeout(r, 5)); // initのfetchを流す
  return w;
}

const flush = () => new Promise((r) => setTimeout(r, 5));

test("angerClassの段階", async () => {
  const w = await boot({ "/api/history": [] });
  assert.equal(w.angerClass(null), "");
  assert.equal(w.angerClass(30), "");
  assert.equal(w.angerClass(31), "a1");
  assert.equal(w.angerClass(44), "a1");
  assert.equal(w.angerClass(45), "a2");
  assert.equal(w.angerClass(69), "a2");
  assert.equal(w.angerClass(70), "a3");
  assert.equal(w.angerClass(100), "a3");
});

test("保存済みの呼を開く: 色分け・状況パネル・声の判定・通話カード", async () => {
  const w = await boot({
    "/api/history/t1": RECORD,
    "/api/history": [{ ...RECORD, messages: undefined }],
  });
  await w.showCall("t1");
  await flush();
  const d = w.document;

  // 吹き出し: 2件、customer側は a3(75)に着色、時刻行にスコア
  const bubbles = d.querySelectorAll("#feed .bubble");
  assert.equal(bubbles.length, 2);
  const cust = d.querySelector(".row.customer .bubble");
  assert.ok(cust.classList.contains("a3"));
  assert.match(cust.querySelector(".time").textContent, /75/);
  // 理由の全文は発話に出さない(状況パネルへ集約した回帰)
  assert.ok(!cust.textContent.includes("責任者要求"));

  // 状況パネル: 現在値・最大値・読み
  assert.equal(d.getElementById("sit-score").textContent, "75");
  assert.match(d.getElementById("sit-max").textContent, /最大 75/);
  assert.equal(d.getElementById("sit-reason").textContent, "責任者要求");

  // 声の判定: 別枠に出て、20点以上の食い違いを明示する(45 - 75 = -30)
  const voice = d.getElementById("sit-voice");
  assert.ok(!voice.classList.contains("hidden"));
  assert.equal(voice.querySelector(".val").textContent, "45");
  assert.match(voice.querySelector(".gap").textContent, /-30/);

  // 通話カード: バッジ・原文引用・JSONリンク
  const card = d.getElementById("card");
  assert.ok(!card.classList.contains("hidden"));
  assert.equal(card.querySelector(".flag").textContent, "カスハラの疑い");
  assert.equal(card.querySelector(".quote").textContent, "責任者を出せよ、今すぐ。");
  assert.equal(card.querySelector("a").getAttribute("href"), "/api/history/t1/card.json");
});

test("ライブ更新: 発話→判定→アラート→通話終了後も状態が残る", async () => {
  const w = await boot({
    "/api/history/t1": { ...RECORD, card: null, live: true, ended_at: null },
    "/api/history": [],
  });
  await w.showCall("t1");
  await flush();
  const d = w.document;

  // 新しい発話が届く
  w.handle({ type: "transcript", contact_id: "t1", speaker: "customer",
             item_id: "x9", text: "新しい発話", final: true, ts: 1700000070 });
  assert.equal(d.querySelectorAll("#feed .bubble").length, 3);

  // 判定が届く: パネル更新+アラート帯+着色
  w.handle({ type: "emotion", contact_id: "t1", item_id: "x9",
             score: 85, reason: "明確な怒り", alert: true });
  assert.equal(d.getElementById("sit-score").textContent, "85");
  assert.ok(d.getElementById("alert").classList.contains("on"));
  assert.match(d.getElementById("alert-title").textContent, /85/);

  // 通話終了でヘッダが再描画されても、状況パネルが「判定待ち」に戻らない
  // (2026-08-03に直したバグの回帰テスト)
  w.handle({ type: "call_ended", contact_id: "t1", live: false,
             ended_at: 1700000080, max_anger: 85 });
  assert.equal(d.getElementById("sit-score").textContent, "85");
  assert.equal(d.getElementById("sit-reason").textContent, "明確な怒り");

  // 別の呼のイベントは表示に影響しない
  w.handle({ type: "emotion", contact_id: "OTHER", item_id: "z1",
             score: 10, reason: "無関係", alert: false });
  assert.equal(d.getElementById("sit-score").textContent, "85");
});

test("カードが無い呼ではカード枠を出さない", async () => {
  const w = await boot({
    "/api/history/t1": { ...RECORD, card: null },
    "/api/history": [],
  });
  await w.showCall("t1");
  await flush();
  assert.ok(w.document.getElementById("card").classList.contains("hidden"));
});
