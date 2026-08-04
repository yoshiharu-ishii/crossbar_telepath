import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { initialState, reducer } from "./store";
import type { CallRecord, RecordingFile, WsEvent } from "./types";
import { Sidebar } from "./components/Sidebar";
import { CallHeader } from "./components/CallHeader";
import { AlertBanner } from "./components/AlertBanner";
import { CardPanel } from "./components/CardPanel";
import { Feed } from "./components/Feed";

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [files, setFiles] = useState<RecordingFile[]>([]);
  // 録音再生中の再生位置(ms)。再生していないときはnull。
  // 発話のaudio_start_msと同じ座標なので、フィードの追従に使える
  const [playhead, setPlayhead] = useState<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const openCall = useCallback(async (id: string, mode: "live" | "history") => {
    try {
      const res = await fetch(`/api/history/${id}`);
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
        const metas = await (await fetch("/api/history")).json();
        dispatch({ type: "history_loaded", metas });
      } catch {
        dispatch({ type: "ws_status", status: "履歴の取得に失敗" });
      }
      try {
        setFiles(await (await fetch("/api/recording-files")).json());
      } catch {
        /* 開発用の一覧なので無くても本体は動く */
      }
    })();
  }, []);

  // WebSocket。live モードなら call_started で自動的に表示を切り替える
  useEffect(() => {
    let ws: WebSocket;
    let closed = false;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => dispatch({ type: "ws_status", status: "待機中" });
      ws.onmessage = (e) => {
        const ev: WsEvent = JSON.parse(e.data);
        dispatch({ type: "ws_event", ev });
      };
      ws.onclose = () => {
        if (closed) return;
        dispatch({ type: "ws_status", status: "切断 — 再接続します" });
        setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      closed = true;
      ws.close();
    };
  }, []);

  // liveモードで未選択なら、進行中の呼を自動で開く。WS接続より前に始まった呼
  // (画面を後から開いた・リロードした場合)はcall_startedが来ないため、
  // イベント頼みだと取りこぼす
  useEffect(() => {
    if (state.mode !== "live" || state.selectedId != null) return;
    const active = [...state.calls.values()]
      .filter((c) => c.live)
      .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))[0];
    if (active) void openCall(active.contact_id, "live");
  }, [state.calls, state.mode, state.selectedId, openCall]);

  const selected = state.selectedId ? state.calls.get(state.selectedId) : undefined;

  return (
    <div className="d-flex flex-column vh-100">
      <header className="d-flex align-items-center gap-3 px-3 py-2 border-bottom bg-body">
        <h1 className="fs-6 fw-semibold m-0">リアルタイム識字</h1>
        <span className="text-secondary small">{state.wsStatus}</span>
      </header>
      <div className="layout flex-grow-1">
        <Sidebar
          state={state}
          files={files}
          onSelect={(id) => openCall(id, "history")}
          onGoLive={() => {
            const active = [...state.calls.values()]
              .filter((c) => c.live)
              .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))[0];
            if (active) openCall(active.contact_id, "live");
            else dispatch({ type: "go_live" });
          }}
          onReplay={async (file) => {
            const res = await fetch(`/api/replay?file=${encodeURIComponent(file)}`, {
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
        <main className="main-pane bg-body-tertiary">
          {selected ? (
            <>
              <CallHeader
                meta={selected}
                situation={state.situation}
                dispatchStatus={(s) => dispatch({ type: "ws_status", status: s })}
                onPlayhead={setPlayhead}
              />
              {state.alert && <AlertBanner alert={state.alert} />}
              <Feed messages={state.messages} meta={selected} playhead={playhead}>
                {/* カードはスクロール領域の中に置く。固定領域に置くと、狭い画面で
                    ヘッダ+カードがフィードを1pxまで潰す(2026-08-04に実際に発生) */}
                {!selected.live && selected.card && <CardPanel meta={selected} />}
              </Feed>
            </>
          ) : (
            <div className="text-center text-secondary p-5">
              <div className="mb-1">🟢 リアルタイム待機中</div>
              架電するか、左の録音ファイルをリプレイしてください。
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
