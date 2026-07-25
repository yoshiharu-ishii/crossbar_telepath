// 呼(contact_id)ごとにカードを作り、その中へ話者別の発言を積む。
// delta は未確定として薄く出し、completed が来たら確定表示に差し替える。

const callsEl = document.getElementById("calls");
const emptyEl = document.getElementById("empty");
const statusEl = document.getElementById("status");
const replayBtn = document.getElementById("replay");

const WHO = { customer: "相手 (FROM_CUSTOMER)", agent: "こちら (TO_CUSTOMER)" };
const calls = new Map(); // contact_id -> {root, body, bubbles}

function clock(ts) {
  return new Date((ts || Date.now() / 1000) * 1000).toLocaleTimeString("ja-JP", { hour12: false });
}

function shortId(id) {
  return id && id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id || "";
}

function callCard(msg) {
  let call = calls.get(msg.contact_id);
  if (call) return call;

  emptyEl.style.display = "none";
  const root = document.createElement("section");
  root.className = "call live";
  root.innerHTML =
    `<div class="call-head">` +
    `<span class="dot"></span><span class="cid"></span>` +
    `<span class="meta"></span><span class="spacer" style="flex:1"></span>` +
    `<span class="badge">通話中</span></div>` +
    `<div class="body"><div class="quiet">音声を待っています…</div></div>`;
  root.querySelector(".cid").textContent = shortId(msg.contact_id);
  const meta = [msg.customer_number, msg.label, clock(msg.ts)].filter(Boolean).join(" · ");
  root.querySelector(".meta").textContent = meta;

  callsEl.prepend(root);
  call = { root, body: root.querySelector(".body"), bubbles: new Map(), empty: true };
  calls.set(msg.contact_id, call);
  return call;
}

function bubbleFor(call, msg) {
  const key = `${msg.speaker}:${msg.item_id}`;
  let el = call.bubbles.get(key);
  if (el) return el;

  if (call.empty) {
    call.body.innerHTML = "";
    call.empty = false;
  }
  const row = document.createElement("div");
  row.className = `row ${msg.speaker}`;
  row.innerHTML =
    `<div class="bubble pending"><div class="who"></div>` +
    `<div class="text"></div><div class="time"></div></div>`;
  row.querySelector(".who").textContent = WHO[msg.speaker] || msg.speaker;
  row.querySelector(".time").textContent = clock(msg.ts);
  call.body.appendChild(row);
  el = row.querySelector(".bubble");
  call.bubbles.set(key, el);
  return el;
}

function handle(msg) {
  switch (msg.type) {
    case "call_started": {
      callCard(msg);
      replayBtn.disabled = false;
      break;
    }
    case "call_ended": {
      const call = calls.get(msg.contact_id);
      if (!call) break;
      call.root.classList.remove("live");
      call.root.querySelector(".badge").textContent = `終了 ${clock(msg.ts)}`;
      if (call.empty) call.body.querySelector(".quiet").textContent = "発話は検出されませんでした。";
      break;
    }
    case "transcript": {
      const call = calls.get(msg.contact_id) || callCard(msg);
      const el = bubbleFor(call, msg);
      const text = el.querySelector(".text");
      if (msg.final) {
        text.textContent = msg.text || text.textContent;
        el.classList.remove("pending");
      } else {
        text.textContent += msg.delta || "";
      }
      break;
    }
    case "error": {
      const call = calls.get(msg.contact_id);
      if (call) {
        const div = document.createElement("div");
        div.className = "quiet";
        div.textContent = `エラー (${msg.speaker}): ${msg.message}`;
        call.body.appendChild(div);
      }
      break;
    }
  }
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => (statusEl.textContent = "待機中");
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => {
    statusEl.textContent = "切断 — 再接続します";
    setTimeout(connect, 1500);
  };
}

replayBtn.onclick = async () => {
  replayBtn.disabled = true;
  try {
    await fetch("/api/replay", { method: "POST" });
  } catch (e) {
    statusEl.textContent = `リプレイ開始に失敗: ${e}`;
  } finally {
    setTimeout(() => (replayBtn.disabled = false), 1000);
  }
};

connect();
