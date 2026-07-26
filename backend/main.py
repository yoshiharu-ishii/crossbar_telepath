"""リアルタイム識字チェックアプリ(PH2)のエントリポイント。

呼の到来はシグナリング(SQS)で知り、音声は通話路(KVS)から受ける。
交換機と同じく制御信号と通話路を分離しているので、呼とストリームの対応を
推測する必要がない。呼はすべて記録され、履歴から選択・リプレイできる。
APIキーはサーバー側にのみ置き、ブラウザには渡さない。

構成: config(設定) / mkv(EBML逐次パース) / audio(リサンプル) /
transcribe(Realtime API) / signaling(呼の受信) / sources(KVS・リプレイ) /
history(呼記録の永続化) / hub(呼のセッションと配信)。
このファイルは組み立てとルーティングだけを持つ。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import history
import signaling
import sources
from config import FRONTEND_DIR, RECORDINGS_DIR
from hub import CallSession, Hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

# 呼ごとのタスク。同時に複数の呼が来ても取り違えない
_sessions: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    watcher = None
    if os.getenv("WATCH_CALLS", "0") == "1":
        watcher = asyncio.create_task(_watch_signaling())
    else:
        log.info("WATCH_CALLS=0 のためシグナリング監視はしない(リプレイのみ)")
    yield
    if watcher:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
    for task in list(_sessions.values()):
        task.cancel()


app = FastAPI(lifespan=lifespan)
hub = Hub()


@app.middleware("http")
async def cache_control(request: Request, call_next):
    """静的ファイルをキャッシュさせない。

    realtime_voiceで踏んだ事故の再発防止: 更新後のHTMLと古いapp.jsの
    組み合わせをブラウザが作ると、要素IDの不一致でスクリプトが例外死し
    「画面が反応しない」状態になる(2026-07-26に実際に発生)。
    """
    response = await call_next(request)
    if request.url.path == "/":
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/static"):
        # 毎回サーバーへ再検証させる(未更新なら304で転送なし)
        response.headers["Cache-Control"] = "no-cache"
    return response


def _start_session(session: CallSession, source) -> None:
    """呼を1本立ち上げる。既に同じ呼が走っていれば何もしない。"""
    if session.contact_id in _sessions and not _sessions[session.contact_id].done():
        log.info("既に処理中の呼: %s", session.contact_id)
        return

    async def runner() -> None:
        try:
            await session.run(source)
        finally:
            _sessions.pop(session.contact_id, None)

    _sessions[session.contact_id] = asyncio.create_task(runner())


async def _watch_signaling() -> None:
    """コールフローからの呼設定を受け取り、呼ごとに受信を始める。"""
    log.info("シグナリング監視を開始")
    async for ev in signaling.poll_call_events():
        if not ev.stream_arn:
            log.warning("StreamARNの無い呼イベントを無視: %s", ev.contact_id)
            continue
        log.info(
            "呼を検出: contact=%s customer=%s fragment=%s",
            ev.contact_id, ev.customer_number, ev.start_fragment,
        )
        session = CallSession(
            hub,
            contact_id=ev.contact_id,
            label=ev.stream_arn.rsplit("/", 2)[-2],
            customer_number=ev.customer_number,
            persist=True,
        )
        _start_session(session, sources.stream_from_kvs(ev.stream_arn, ev.start_fragment))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)


@app.get("/api/history")
def api_history() -> list[dict]:
    """呼の一覧。処理中+終了直後(メモリ)+保存済み(ディスク)を新しい順で。"""
    in_memory = [c.meta() for c in hub.active.values()] + [
        c.meta() for c in hub.recent.values()
    ]
    seen = {c["contact_id"] for c in in_memory}
    saved = [r for r in history.list_records() if r["contact_id"] not in seen]
    return sorted(in_memory + saved, key=lambda r: r.get("started_at") or 0, reverse=True)


@app.get("/api/history/{contact_id}")
def api_history_one(contact_id: str) -> dict:
    """1つの呼の記録(メモリ上を優先、なければディスクから)。"""
    call = hub.get_record(contact_id)
    if call is not None:
        return call.as_dict()
    try:
        rec = history.load_record(contact_id)
    except ValueError:
        raise HTTPException(400, "不正なcontact_id")
    if rec is None:
        raise HTTPException(404, f"呼 {contact_id} の記録がありません")
    return rec


@app.post("/api/replay")
async def api_replay(
    file: str = "call.mkv", contact_id: str | None = None, speed: float = 1.0
) -> dict:
    """録音を流して、架電せずに画面まで通しで試す。

    contact_id を渡すと過去の呼の録音を、file なら recordings/ 直下のMKVを流す。
    """
    if contact_id:
        try:
            path = history.recording_path(contact_id)
        except ValueError:
            raise HTTPException(400, "不正なcontact_id")
        label = f"replay:{contact_id[:8]}"
    else:
        path = RECORDINGS_DIR / file
        if path.parent != RECORDINGS_DIR:
            raise HTTPException(400, "fileはrecordings/直下のみ")
        label = f"replay:{file}"
    if not path.exists():
        raise HTTPException(404, f"{path.name} がありません")

    new_id = f"replay-{uuid.uuid4().hex[:8]}"
    session = CallSession(hub, contact_id=new_id, label=label)
    _start_session(session, sources.replay_file(path, speed))
    return {"status": "started", "contact_id": new_id, "source": path.name, "speed": speed}


@app.get("/api/streams")
def api_streams() -> list[dict]:
    """KVS上の通話ストリーム(シグナリングが動かないときの切り分け用)。"""
    return [
        {"name": s["StreamName"], "arn": s["StreamARN"], "created": str(s["CreationTime"])}
        for s in sources.list_call_streams()
    ]


@app.get("/api/health")
def api_health() -> dict:
    return {
        "status": "ok",
        "watching": os.getenv("WATCH_CALLS", "0") == "1",
        "active_calls": len(_sessions),
        "ts": time.time(),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
