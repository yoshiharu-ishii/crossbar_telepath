// 呼の履歴リスト(左)と、選択した呼の文字起こし(右)。
// 一覧と過去の発言はRESTから取り、進行中の差分はWebSocketで受ける。
// WSの全イベントは contact_id を持つので、選択中の呼のものだけ描画する。

const listEl = document.getElementById("list");
const listEmptyEl = document.getElementById("list-empty");
const feedEl = document.getElementById("feed");
const headEl = document.getElementById("call-head");
const statusEl = document.getElementById("status");
const replayFileBtn = document.getElementById("replay-file");

const WHO = { customer: "相手 (FROM_CUSTOMER)", agent: "こちら (TO_CUSTOMER)" };
const calls = new Map(); // contact_id -> meta
let selectedId = null;
let bubbles = new Map(); // 選択中の呼の item_id -> element

function clock(ts) {
  return ts ? new Date(ts * 1000).toLocaleTimeString("ja-JP", { hour12: false }) : "";
}
function day(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit" }) : "";
}
function shortId(id) {
  return id && id.length > 12 ? `${id.slice(0, 8)}…` : id || "";
}

// ---- 左ペイン: 呼リスト ----

function renderList() {
  const metas = [...calls.values()].sort((a, b) => (b.started_at || 0) - (a.started_at || 0));
  listEmptyEl.style.display = metas.length ? "none" : "";
  listEl.innerHTML = "";
  for (const m of metas) {
    const div = document.createElement("div");
    div.className = "item" + (m.contact_id === selectedId ? " selected" : "");
    div.innerHTML =
      `<div class="line1"><span class="dot"></span><span class="num"></span></div>` +
      `<div class="meta"></div>`;
    if (m.live) div.querySelector(".dot").classList.add("live");
    // 主キーはCallID。番号やリプレイ元はメタ行に回す
    div.querySelector(".num").textContent = shortId(m.contact_id);
    div.querySelector(".meta").textContent = [
      `${day(m.started_at)} ${clock(m.started_at)}`,
      m.live ? "通話中" : `${m.message_count ?? 0}件`,
      m.customer_number || (m.label?.startsWith("replay:") ? m.label : null),
      m.has_recording ? "録音あり" : null,
    ].filter(Boolean).join(" · ");
    div.onclick = () => selectCall(m.contact_id);
    listEl.appendChild(div);
  }
}

function upsertCall(meta) {
  calls.set(meta.contact_id, { ...calls.get(meta.contact_id), ...meta });
  renderList();
}

// ---- 右ペイン: 選択した呼 ----

function renderHead(m) {
  headEl.innerHTML = "";
  const parts = [
    m.live ? "🟢 通話中" : `終了 ${clock(m.ended_at)}`,
    shortId(m.contact_id),
    m.customer_number,
    `開始 ${day(m.started_at)} ${clock(m.started_at)}`,
  ].filter(Boolean);
  for (const p of parts) {
    const s = document.createElement("span");
    s.textContent = p;
    headEl.appendChild(s);
  }
  // 呼の操作卓: 録音の再生/停止と、同じCallIDでの再文字起こし
  if (!m.live && m.has_recording) {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "none";
    audio.src = `/api/recordings/${m.contact_id}.wav`;
    audio.title = "左=相手 / 右=こちら";
    audio.style.height = "32px";
    headEl.appendChild(audio);

    const b = document.createElement("button");
    b.textContent = "再文字起こし";
    b.title = "録音から文字起こしを作り直す(履歴は増えない)";
    b.onclick = async () => {
      b.disabled = true;
      const res = await fetch(`/api/reprocess/${m.contact_id}?speed=2.0`, { method: "POST" })
        .catch(() => null);
      if (!res?.ok) {
        const body = res ? await res.json().catch(() => ({})) : {};
        statusEl.textContent = body.detail || "再文字起こしを開始できませんでした";
        setTimeout(() => (statusEl.textContent = "待機中"), 3000);
        b.disabled = false;
      }
    };
    headEl.appendChild(b);
  }
}

function addBubble(msg) {
  const key = `${msg.speaker}:${msg.item_id}`;
  let el = bubbles.get(key);
  if (el) return el;
  const row = document.createElement("div");
  row.className = `row ${msg.speaker}`;
  row.innerHTML =
    `<div class="bubble pending"><div class="who"></div><div class="text"></div><div class="time"></div></div>`;
  row.querySelector(".who").textContent = WHO[msg.speaker] || msg.speaker;
  row.querySelector(".time").textContent = clock(msg.ts);
  feedEl.appendChild(row);
  el = row.querySelector(".bubble");
  bubbles.set(key, el);
  return el;
}

function applyTranscript(msg) {
  const el = addBubble(msg);
  const text = el.querySelector(".text");
  if (msg.final) {
    text.textContent = msg.text || text.textContent;
    el.classList.remove("pending");
  } else {
    text.textContent += msg.delta || "";
  }
  feedEl.scrollTop = feedEl.scrollHeight;
}

async function selectCall(id) {
  selectedId = id;
  bubbles = new Map();
  feedEl.innerHTML = "";
  renderList();
  try {
    const rec = await (await fetch(`/api/history/${id}`)).json();
    upsertCall({ ...rec, messages: undefined });
    renderHead(calls.get(id));
    if (!rec.messages?.length) {
      feedEl.innerHTML = `<div class="quiet">この呼にはまだ発話がありません。</div>`;
    } else {
      for (const m of rec.messages) applyTranscript(m);
    }
  } catch {
    feedEl.innerHTML = `<div class="quiet">記録を読み込めませんでした。</div>`;
  }
}

// ---- WebSocket ----

function handle(msg) {
  switch (msg.type) {
    case "call_started": {
      upsertCall(msg);
      // 新しい呼(実通話・リプレイとも)は自動で選択して追いかける
      selectCall(msg.contact_id);
      break;
    }
    case "call_ended": {
      upsertCall(msg);
      if (msg.contact_id === selectedId) renderHead(calls.get(msg.contact_id));
      break;
    }
    case "transcript": {
      const m = calls.get(msg.contact_id);
      if (m && msg.final) {
        m.message_count = (m.message_count ?? 0) + 1;
        renderList();
      }
      if (msg.contact_id === selectedId) {
        if (feedEl.querySelector(".quiet")) feedEl.innerHTML = "";
        applyTranscript(msg);
      }
      break;
    }
    case "error": {
      if (msg.contact_id === selectedId) {
        const div = document.createElement("div");
        div.className = "quiet";
        div.textContent = `エラー (${msg.speaker}): ${msg.message}`;
        feedEl.appendChild(div);
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

async function replay(params) {
  const q = new URLSearchParams(params);
  try {
    const res = await fetch(`/api/replay?${q}`, { method: "POST" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      statusEl.textContent = body.detail || `リプレイ開始に失敗 (${res.status})`;
      setTimeout(() => (statusEl.textContent = "待機中"), 3000);
    }
  } catch (e) {
    statusEl.textContent = `リプレイ開始に失敗: ${e}`;
  }
}

replayFileBtn.onclick = () => replay({ file: "call.mkv" });

async function init() {
  try {
    const metas = await (await fetch("/api/history")).json();
    for (const m of metas) calls.set(m.contact_id, m);
    renderList();
    if (metas.length) selectCall(metas[0].contact_id);
  } catch {
    statusEl.textContent = "履歴の取得に失敗";
  }
  connect();
}

init();
