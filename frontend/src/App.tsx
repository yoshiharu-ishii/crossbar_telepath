import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { initialState, reducer } from "./store";
import { apiFetch, wsUrl } from "./api";
import { alertBeep } from "./sound";
import type { CallRecord, RecordingFile, WsEvent } from "./types";
import { Menu } from "./components/Menu";
import { Dashboard } from "./components/Dashboard";
import { Files } from "./components/Files";
import { CallHeader } from "./components/CallHeader";
import { AlertBanner } from "./components/AlertBanner";
import { CardPanel } from "./components/CardPanel";
import { Feed } from "./components/Feed";

export default function App({
  identity,
  onLogout,
  devTools = true, // 単体テスト・AuthGate未経由(素の開発)では見せる
}: {
  identity?: { email: string; role: "sv" | "operator" } | null;
  onLogout?: () => void;
  devTools?: boolean;
} = {}) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [files, setFiles] = useState<RecordingFile[]>([]);
  // 録音再生中の再生位置(ms)。再生していないときはnull。
  // 発話のaudio_start_msと同じ座標なので、フィードの追従に使える
  const [playhead, setPlayhead] = useState<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const openCall = useCallback(async (id: string, mode: "live" | "history") => {
    try {
      const res = await apiFetch(`/api/history/${id}`);
      if (!res.ok) return;
      const record: CallRecord = await res.json();
      dispatch({ type: "open_call", record, mode });
    } catch {
      /* 一覧は生きているので黙って何もしない */
    }
  }, []);

  // 初期ロード: 履歴+録音ファイル
  useEffect(() => {
    (async () => {
      try {
        const metas = await (await apiFetch("/api/history")).json();
        dispatch({ type: "history_loaded", metas });
      } catch {
        dispatch({ type: "ws_status", status: "履歴の取得に失敗" });
      }
      try {
        setFiles(await (await apiFetch("/api/recording-files")).json());
      } catch {
        /* 開発用の一覧なので無くても本体は動く */
      }
    })();
  }, []);

  // WebSocket。live モードなら call_started で自動的に表示を切り替える
  useEffect(() => {
    let ws: WebSocket;
    let closed = false;
    const connect = async () => {
      ws = new WebSocket(await wsUrl());
      ws.onopen = () => dispatch({ type: "ws_status", status: "待機中" });
      ws.onmessage = (e) => {
        const ev: WsEvent = JSON.parse(e.data);
        dispatch({ type: "ws_event", ev });
      };
      ws.onclose = (e) => {
        if (closed) return;
        if (e.code === 4401) {
          location.reload(); // 認証切れ → ログインへ
          return;
        }
        dispatch({ type: "ws_status", status: "切断 — 再接続します" });
        setTimeout(connect, 1500);
      };
    };
    void connect();
    return () => {
      closed = true;
      ws.close();
    };
  }, []);

  // リアルタイム追従(mode=live)で未選択なら、進行中の呼を自動で開く。
  // WS接続より前に始まった呼はcall_startedが来ないため、イベント頼みだと取りこぼす。
  // 監視卓(dashboard)は自動で画面を奪わない——SVの視点を勝手に動かさない
  useEffect(() => {
    if (state.view !== "detail" || state.mode !== "live" || state.selectedId != null) return;
    const active = [...state.calls.values()]
      .filter((c) => c.live)
      .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))[0];
    if (active) void openCall(active.contact_id, "live");
  }, [state.calls, state.mode, state.selectedId, openCall]);

  const selected = state.selectedId ? state.calls.get(state.selectedId) : undefined;
  const isOperator = identity?.role === "operator";

  // アラート音はSV(監視卓)だけ。応対者は通話の中にいる本人であり、
  // 相手の怒りを一番よく知っている——音は集中を奪うだけ(docs/roadmap.md 3.3)
  useEffect(() => {
    if (state.alert && !isOperator) alertBeep();
  }, [state.alert, isOperator]);

  return (
    <div className="d-flex flex-column vh-100">
      <header className="d-flex align-items-center gap-3 px-3 py-2 border-bottom bg-body">
        <h1 className="fs-6 fw-semibold m-0">リアルタイム識字</h1>
        <span className="text-secondary small">{state.wsStatus}</span>
        {identity && (
          <div className="ms-auto d-flex align-items-center gap-2 small">
            <span className={`badge rounded-pill ${identity.role === "sv" ? "text-bg-primary" : "text-bg-secondary"}`}>
              {identity.role === "sv" ? "SV(監視卓)" : "応対者"}
            </span>
            <span className="text-secondary d-none d-md-inline">{identity.email}</span>
            <button className="btn btn-sm btn-outline-secondary" onClick={onLogout}>
              ログアウト
            </button>
          </div>
        )}
      </header>
      <div className="layout flex-grow-1">
        <Menu
          state={state}
          devTools={devTools}
          liveCount={[...state.calls.values()].filter((c) => c.live).length}
          onSelect={(view) => dispatch({ type: "set_view", view })}
          onGoLive={() => {
            const active = [...state.calls.values()]
              .filter((c) => c.live)
              .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))[0];
            if (active) openCall(active.contact_id, "live");
            else dispatch({ type: "go_live" });
          }}
        />
        <main className="main-pane bg-body-tertiary">
          {state.view === "dashboard" && (
            <Dashboard
              calls={[...state.calls.values()]}
              myEmail={identity?.email}
              onOpen={(id) => openCall(id, "history")}
              onClaim={async (id) => {
                const res = await apiFetch(`/api/calls/${id}/claim`, { method: "POST" })
                  .catch(() => null);
                if (!res?.ok) {
                  const body = res ? await res.json().catch(() => ({})) : {};
                  dispatch({ type: "ws_status", status: body.detail || "取れませんでした" });
                  setTimeout(() => dispatch({ type: "ws_status", status: "待機中" }), 3000);
                }
              }}
            />
          )}
          {state.view === "files" && (
            <Files
              files={files}
              onReplay={async (file) => {
                const res = await apiFetch(`/api/replay?file=${encodeURIComponent(file)}`, {
                  method: "POST",
                }).catch(() => null);
                if (!res?.ok) {
                  const body = res ? await res.json().catch(() => ({})) : {};
                  dispatch({ type: "ws_status", status: body.detail || "リプレイを開始できませんでした" });
                  setTimeout(() => dispatch({ type: "ws_status", status: "待機中" }), 3000);
                } else {
                  dispatch({ type: "go_live" });
                }
              }}
            />
          )}
          {state.view === "detail" &&
            (selected ? (
              <>
                <div className="px-3 pt-2 bg-body border-bottom-0">
                  <button
                    className="btn btn-sm btn-link text-decoration-none px-0"
                    onClick={() => dispatch({ type: "set_view", view: "dashboard" })}
                  >
                    ← 監視卓へ
                  </button>
                </div>
                <CallHeader
                  meta={selected}
                  situation={state.situation}
                  canReprocess={!isOperator}
                  dispatchStatus={(s) => dispatch({ type: "ws_status", status: s })}
                  onPlayhead={setPlayhead}
                />
                {state.alert && <AlertBanner alert={state.alert} />}
                <Feed messages={state.messages} meta={selected} playhead={playhead}>
                  {/* カードはスクロール領域の中に置く。固定領域に置くと、狭い画面で
                      ヘッダ+カードがフィードを1pxまで潰す(2026-08-04に実際に発生)。
                      応対者には出さない——「後」の記録・評価はSVのもの(roadmap 3.3) */}
                  {!selected.live && selected.card && !isOperator && <CardPanel meta={selected} />}
                </Feed>
              </>
            ) : (
              <div className="text-center text-secondary p-5">
                <div className="mb-1">🟢 リアルタイム待機中</div>
                架電するか、録音ファイルをリプレイしてください。
              </div>
            ))}
        </main>
      </div>
    </div>
  );
}
