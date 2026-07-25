// サーバーから流れてくる文字起こしイベントをチャット表示する。
// delta は未確定として薄く出し、completed が来たら確定表示に差し替える。

const feed = document.getElementById("feed");
const empty = document.getElementById("empty");
const dot = document.getElementById("dot");
const label = document.getElementById("label");
const replayBtn = document.getElementById("replay");

const WHO = { customer: "相手 (FROM_CUSTOMER)", agent: "こちら (TO_CUSTOMER)" };
const bubbles = new Map(); // item_id -> element

function clock(ts) {
  const d = ts ? new Date(ts * 1000) : new Date();
  return d.toLocaleTimeString("ja-JP", { hour12: false });
}

function bubbleFor(msg) {
  const key = `${msg.speaker}:${msg.item_id}`;
  let el = bubbles.get(key);
  if (el) return el;

  empty.style.display = "none";
  const row = document.createElement("div");
  row.className = `row ${msg.speaker}`;
  row.innerHTML =
    `<div class="bubble pending">` +
    `<div class="who"></div><div class="text"></div><div class="time"></div></div>`;
  row.querySelector(".who").textContent = WHO[msg.speaker] || msg.speaker;
  row.querySelector(".time").textContent = clock(msg.ts);
  feed.appendChild(row);
  el = row.querySelector(".bubble");
  bubbles.set(key, el);
  window.scrollTo(0, document.body.scrollHeight);
  return el;
}

function system(text) {
  const div = document.createElement("div");
  div.className = "sys";
  div.textContent = text;
  feed.appendChild(div);
  window.scrollTo(0, document.body.scrollHeight);
}

function handle(msg) {
  if (msg.type === "call_state") {
    const active = msg.status === "active";
    dot.classList.toggle("active", active);
    label.textContent = active ? `通話中 ${msg.label || ""}` : "待機中";
    if (active) {
      feed.innerHTML = "";
      bubbles.clear();
      empty.style.display = "none";
      system(`通話開始 ${clock(msg.ts)}`);
    } else if (bubbles.size) {
      system(`通話終了 ${clock(msg.ts)}`);
    }
    replayBtn.disabled = active;
    return;
  }
  if (msg.type === "transcript") {
    const el = bubbleFor(msg);
    const text = el.querySelector(".text");
    if (msg.final) {
      text.textContent = msg.text || text.textContent;
      el.classList.remove("pending");
    } else {
      text.textContent += msg.delta || "";
    }
    window.scrollTo(0, document.body.scrollHeight);
    return;
  }
  if (msg.type === "error") {
    system(`エラー (${msg.speaker}): ${msg.message}`);
  }
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 1500);
}

replayBtn.onclick = async () => {
  replayBtn.disabled = true;
  try {
    await fetch("/api/replay", { method: "POST" });
  } catch (e) {
    system(`リプレイ開始に失敗: ${e}`);
    replayBtn.disabled = false;
  }
};

connect();
