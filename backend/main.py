"""リアルタイム識字チェックアプリ(PH2)のエントリポイント。

KVS(またはローカル録音のリプレイ)から通話音声を受け取り、話者別に文字起こしして
ブラウザへ流す。APIキーはサーバー側にのみ置き、ブラウザには渡さない。

構成: config(設定) / mkv(EBML逐次パース) / audio(リサンプル) /
transcribe(Realtime API) / sources(KVS・リプレイ) / hub(セッションと配信)。
このファイルはFastAPIの組み立てとルーティングだけを持つ。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import sources
from config import FRONTEND_DIR, KVS_POLL_INTERVAL, RECORDINGS_DIR
from hub import CallSession, Hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    watcher = None
    if os.getenv("WATCH_KVS", "0") == "1":
        watcher = asyncio.create_task(_watch_kvs())
    else:
        log.info("WATCH_KVS=0 のためKVS監視はしない(リプレイのみ)")
    yield
    if watcher:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher


app = FastAPI(lifespan=lifespan)
hub = Hub()

# 同時に扱う通話は1本。次の通話が来たら前のセッションは畳む
_current: asyncio.Task | None = None


async def _run_session(label: str, source) -> None:
    global _current
    if _current and not _current.done():
        _current.cancel()
    session = CallSession(hub, label)
    _current = asyncio.create_task(session.run(source))
    await _current


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


@app.get("/api/streams")
def api_streams() -> list[dict]:
    """KVS上の通話ストリーム(デバッグ用)。"""
    return [
        {"name": s["StreamName"], "arn": s["StreamARN"], "created": str(s["CreationTime"])}
        for s in sources.list_call_streams()
    ]


@app.post("/api/replay")
async def api_replay(file: str = "call.mkv", speed: float = 1.0) -> dict:
    """録音済みMKVを流して、架電せずに画面まで通しで試す。"""
    path = RECORDINGS_DIR / file
    if not path.exists():
        raise HTTPException(404, f"{path} がありません")
    asyncio.create_task(_run_session(f"replay:{file}", sources.replay_file(path, speed)))
    return {"status": "started", "file": file, "speed": speed}


async def _watch_kvs() -> None:
    """新しい通話ストリームを見つけたら受信を始める。"""
    seen = {s["StreamARN"] for s in await asyncio.to_thread(sources.list_call_streams)}
    log.info("KVS watcher started (既存 %d 本は無視)", len(seen))
    while True:
        try:
            streams = await asyncio.to_thread(sources.list_call_streams)
            for s in reversed(streams):
                if s["StreamARN"] in seen:
                    continue
                seen.add(s["StreamARN"])
                log.info("new call stream: %s", s["StreamName"])
                asyncio.create_task(
                    _run_session(s["StreamName"], sources.stream_from_kvs(s["StreamARN"]))
                )
        except Exception:
            log.exception("KVS watcher error")
        await asyncio.sleep(KVS_POLL_INTERVAL)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
