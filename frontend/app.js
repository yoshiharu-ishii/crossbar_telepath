// 左ペイン = 音源の一覧(ライブ待機 / 呼の履歴 / 録音ファイル)、右ペイン = 選んだものの表示。
//
// モードが2つある:
// - live:    新しい呼が来たら自動で表示を切り替えて追いかける(待機画面を含む)
// - history: 選択した呼を見る。新しい呼が来ても画面を奪われない
// 一覧と過去の発言はRESTから取り、進行中の差分はWebSocketで受ける。

const liveItemEl = document.getElementById("live-item");
const listEl = document.getElementById("list");
const listEmptyEl = document.getElementById("list-empty");
const filesEl = document.getElementById("files");
const feedEl = document.getElementById("feed");
const headEl = document.getElementById("call-head");
const statusEl = document.getElementById("status");
const alertEl = document.getElementById("alert");
const alertTitleEl = document.getElementById("alert-title");
const alertReasonEl = document.getElementById("alert-reason");

const WHO = { customer: "相手 (FROM_CUSTOMER)", agent: "こちら (TO_CUSTOMER)" };
const calls = new Map(); // contact_id -> meta

// 怒り度の段階。閾値(既定70)以上が「明確な怒り」
const ANGER_ALERT = 70;
function angerClass(score) {
  if (score == null) return "";
  if (score >= ANGER_ALERT) return "a3";
  if (score >= 45) return "a2";
  if (score >= 31) return "a1";
  return "";
}
let mode = "live";
let selectedId = null; // 右ペインに表示中の呼
let bubbles = new Map();
// 表示中の呼の状態。ヘッダは通話終了などで再描画されるので、
// 最後の判定をここに持っておかないと状況パネルが空に戻ってしまう
let maxAnger = null;
let curAnger = null;
let curReason = "";

function clock(ts) {
  return ts ? new Date(ts * 1000).toLocaleTimeString("ja-JP", { hour12: false }) : "";
}
function day(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit" }) : "";
}
function shortId(id) {
  return id && id.length > 12 ? `${id.slice(0, 8)}…` : id || "";
}
function liveCall() {
  return [...calls.values()]
    .filter((c) => c.live)
    .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))[0];
}

// ---- 左ペイン ----

function renderLiveItem() {
  const active = liveCall();
  liveItemEl.innerHTML =
    `<div class="item${mode === "live" ? " selected" : ""}">` +
    `<div class="line1"><span class="dot${active ? " live" : ""}"></span>` +
    `<span class="num">リアルタイム</span></div><div class="meta"></div></div>`;
  liveItemEl.querySelector(".meta").textContent = active
    ? `通話中 · ${shortId(active.contact_id)}`
    : "待機中 · 呼が来ると自動表示";
  liveItemEl.querySelector(".item").onclick = goLive;
}

function renderList() {
  const metas = [...calls.values()].sort((a, b) => (b.started_at || 0) - (a.started_at || 0));
  listEmptyEl.style.display = metas.length ? "none" : "";
  listEl.innerHTML = "";
  for (const m of metas) {
    const div = document.createElement("div");
    div.className =
      "item" + (mode === "history" && m.contact_id === selectedId ? " selected" : "");
    div.innerHTML =
      `<div class="line1"><span class="dot"></span><span class="num"></span></div>` +
      `<div class="meta"></div>`;
    if (m.live) div.querySelector(".dot").classList.add("live");
    div.querySelector(".num").textContent = shortId(m.contact_id);
    if (m.max_anger != null) {
      const b = document.createElement("span");
      b.className = "badge-anger";
      b.textContent = `怒り ${m.max_anger}`;
      div.querySelector(".line1").appendChild(b);
    }
    div.querySelector(".meta").textContent = [
      `${day(m.started_at)} ${clock(m.started_at)}`,
      m.live ? "通話中" : `${m.message_count ?? 0}件`,
      m.customer_number || (m.label?.startsWith("replay:") ? m.label : null),
      m.has_recording ? "録音あり" : null,
    ].filter(Boolean).join(" · ");
    div.onclick = () => {
      mode = "history";
      showCall(m.contact_id);
    };
    listEl.appendChild(div);
  }
  renderLiveItem();
}

async function renderFiles() {
  let files = [];
  try {
    files = await (await fetch("/api/recording-files")).json();
  } catch { /* 一覧が取れなくても本体機能には影響しない */ }
  filesEl.innerHTML = "";
  for (const f of files) {
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML =
      `<div class="line1"><span class="dot"></span><span class="num"></span></div>` +
      `<div class="meta"></div>`;
    div.querySelector(".num").textContent = f.file;
    div.querySelector(".meta").textContent =
      `${Math.round(f.size / 1024)} KB · クリックでリプレイ`;
    div.onclick = async () => {
      mode = "live"; // リプレイは開始したら追いかける
      const res = await fetch(`/api/replay?file=${encodeURIComponent(f.file)}`, { method: "POST" })
        .catch(() => null);
      if (!res?.ok) {
        const body = res ? await res.json().catch(() => ({})) : {};
        statusEl.textContent = body.detail || "リプレイを開始できませんでした";
        setTimeout(() => (statusEl.textContent = "待機中"), 3000);
      }
    };
    filesEl.appendChild(div);
  }
}

function upsertCall(meta) {
  calls.set(meta.contact_id, { ...calls.get(meta.contact_id), ...meta });
  renderList();
}

// ---- 右ペイン ----

function renderStandby() {
  selectedId = null;
  bubbles = new Map();
  headEl.innerHTML = `<span>🟢 リアルタイム待機中</span><span>呼が来るとここに自動表示されます</span>`;
  feedEl.innerHTML = `<div class="quiet">架電するか、左の録音ファイルをリプレイしてください。</div>`;
}

function goLive() {
  mode = "live";
  const active = liveCall();
  if (active) showCall(active.contact_id);
  else {
    renderStandby();
    renderList();
  }
}

function renderHead(m) {
  headEl.innerHTML = "";
  const parts = [
    m.live ? "🟢 通話中" : `終了 ${clock(m.ended_at)}`,
    shortId(m.contact_id),
    m.customer_number,
    `開始 ${day(m.started_at)} ${clock(m.started_at)}`,
  ].filter(Boolean);
  const left = document.createElement("div");
  left.className = "head-left";
  const meta = document.createElement("div");
  meta.className = "head-meta";
  for (const p of parts) {
    const s = document.createElement("span");
    s.textContent = p;
    meta.appendChild(s);
  }
  left.appendChild(meta);

  // 呼の操作卓: 録音の再生/停止と、同じCallIDでの再文字起こし
  if (!m.live && m.has_recording) {
    const ctl = document.createElement("div");
    ctl.className = "head-ctl";
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "none";
    audio.src = `/api/recordings/${m.contact_id}.wav`;
    audio.title = "左=相手 / 右=こちら";
    audio.style.height = "32px";
    ctl.appendChild(audio);

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
    ctl.appendChild(b);
    left.appendChild(ctl);
  }
  headEl.appendChild(left);

  // 状況パネル(操作卓の右)。バロメータは「今の状態」、脇に呼全体の最大値
  const sit = document.createElement("div");
  sit.id = "situation";
  sit.innerHTML =
    `<div id="sit-top"><span id="sit-label">相手の状態</span>` +
    `<span id="sit-max"></span><span id="sit-score">—</span></div>` +
    `<div id="gauge"><span id="gauge-bar"></span></div>` +
    `<div id="sit-reason"></div>`;
  headEl.appendChild(sit);
  if (m.max_anger != null && (maxAnger == null || m.max_anger > maxAnger)) maxAnger = m.max_anger;
  setSituation(curAnger, curReason);
}

function addBubble(msg) {
  const key = `${msg.speaker}:${msg.item_id}`;
  let el = bubbles.get(key);
  if (el) return el;
  const row = document.createElement("div");
  row.className = `row ${msg.speaker}`;
  row.innerHTML =
    `<div class="bubble pending"><div class="who"></div><div class="text"></div>` +
    `<div class="seg"></div><div class="time"></div></div>`;
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
    addPlayButton(el, msg);
    // 保存済みの記録には判定結果が乗っている
    if (msg.anger_score != null) {
      applyAnger({ item_id: msg.item_id, score: msg.anger_score, reason: msg.anger_reason });
    }
  } else {
    text.textContent += msg.delta || "";
  }
  feedEl.scrollTop = feedEl.scrollHeight;
}

// 発話区間だけを再生する。文字起こしが合っているか耳で確かめるため
let segAudio = null;
function playSegment(contactId, startMs, endMs, btn) {
  if (segAudio) { segAudio.pause(); document.querySelectorAll(".play-seg.playing").forEach(b => b.classList.remove("playing")); }
  const q = new URLSearchParams({ start_ms: Math.round(startMs), end_ms: Math.round(endMs) });
  segAudio = new Audio(`/api/recordings/${contactId}.wav?${q}`);
  btn.classList.add("playing");
  segAudio.onended = () => btn.classList.remove("playing");
  segAudio.onerror = () => btn.classList.remove("playing");
  segAudio.play().catch(() => btn.classList.remove("playing"));
}

// 発話に再生ボタンを付ける。録音があり、音声内の位置が分かるときだけ。
// 位置は再文字起こしのときに付くので、古い呼では欠けている
function addPlayButton(el, msg) {
  const call = calls.get(msg.contact_id || selectedId);
  if (!call?.has_recording) return;
  const slot = el.querySelector(".seg");
  if (!slot || slot.dataset.done) return;
  slot.dataset.done = "1";

  if (msg.audio_start_ms == null) {
    // なぜ聞けないのかを画面で分かるようにする(黙って何も出さない方が不親切)
    const hint = document.createElement("span");
    hint.className = "seg-hint";
    hint.textContent = "位置情報なし — 「再文字起こし」で付きます";
    slot.appendChild(hint);
    return;
  }
  const b = document.createElement("button");
  b.className = "play-seg";
  const dur = ((msg.audio_end_ms - msg.audio_start_ms) / 1000).toFixed(1);
  b.textContent = `▶ この発話を聞く (${dur}秒)`;
  b.onclick = () => playSegment(call.contact_id, msg.audio_start_ms, msg.audio_end_ms, b);
  slot.appendChild(b);
}

function angerColor(s) {
  return s >= ANGER_ALERT ? "#e2564a" : s >= 45 ? "#ef9a72" : s >= 31 ? "#d8a13c" : "#2e9e5b";
}

// 状況パネル。バロメータは「今この瞬間の状態」を出す(累積ではない)。
// 相手が落ち着けば下がってほしい——オペレータに「もう戻っていい」を伝えるため
function setSituation(score, reason) {
  const bar = document.getElementById("gauge-bar");
  const val = document.getElementById("sit-score");
  const rea = document.getElementById("sit-reason");
  const mx = document.getElementById("sit-max");
  if (!bar || !val) return;
  const s = score == null ? 0 : score;
  bar.style.width = `${s}%`;
  bar.style.background = angerColor(s);
  val.textContent = score == null ? "—" : String(score);
  val.style.color = score == null ? "var(--muted)" : angerColor(s);
  if (rea) rea.textContent = reason || "";
  if (mx) mx.textContent = maxAnger == null ? "" : `最大 ${maxAnger}`;
}

// 判定結果を反映する。スコアの意味は「その発話時点での会話の状態」。
// 発話には色だけ乗せ、読み(理由)は状況パネルに集約する
function applyAnger(msg) {
  const el = bubbles.get(`customer:${msg.item_id}`);
  if (el) {
    el.classList.remove("a1", "a2", "a3");
    const cls = angerClass(msg.score);
    if (cls) el.classList.add(cls);
    const t = el.querySelector(".time");
    if (t && !t.dataset.scored) {
      t.dataset.scored = "1";
      const s = document.createElement("span");
      s.className = "score";
      s.textContent = ` · ${msg.score}`;
      s.style.color = angerColor(msg.score);
      t.appendChild(s);
    }
  }
  if (maxAnger == null || msg.score > maxAnger) maxAnger = msg.score;
  curAnger = msg.score;
  curReason = msg.reason || "";
  setSituation(curAnger, curReason);
  const cur = calls.get(selectedId);
  if (cur && (cur.max_anger == null || msg.score > cur.max_anger)) {
    cur.max_anger = msg.score;
    renderList();
  }
}

function showAlert(msg) {
  alertTitleEl.textContent = `⚠ 相手が強い怒りを示しています(${msg.score})`;
  alertReasonEl.textContent = msg.reason || "";
  alertEl.classList.add("on");
}

async function showCall(id) {
  selectedId = id;
  alertEl.classList.remove("on");
  bubbles = new Map();
  maxAnger = null; curAnger = null; curReason = "";  // 呼を切り替えたら状態を持ち越さない
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
      if (mode === "live") showCall(msg.contact_id);
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
    case "emotion": {
      if (msg.contact_id !== selectedId) break;
      applyAnger(msg);
      if (msg.alert) showAlert(msg);
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

async function init() {
  try {
    const metas = await (await fetch("/api/history")).json();
    for (const m of metas) calls.set(m.contact_id, m);
  } catch {
    statusEl.textContent = "履歴の取得に失敗";
  }
  renderFiles();
  goLive(); // 初期表示はライブ待機(通話中の呼があればそれを表示)
  connect();
}

init();
