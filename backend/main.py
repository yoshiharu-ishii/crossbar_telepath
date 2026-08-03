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
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import audio
import history
import signaling
import sources
import storage
from config import FRONTEND_DIR, LOG_LEVEL, RECORDINGS_DIR, WATCH_CALLS
from hub import CallSession, Hub

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

# 呼ごとのタスク。同時に複数の呼が来ても取り違えない
_sessions: dict[str, asyncio.Task] = {}
# シグナリング監視タスク。health で生死を見るためモジュール変数に置く
_watcher: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    history.init()
    log.info("呼の記録: %s / 録音: %s", history.backend(), "s3" if storage.enabled() else "files")
    global _watcher
    watcher = None
    if WATCH_CALLS:
        watcher = _watcher = asyncio.create_task(_watch_forever())
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
    """HTMLはキャッシュさせず、ハッシュ付きアセットは長期キャッシュさせる。

    かつて「更新後のHTMLと古いapp.js」の組み合わせでスクリプトが例外死する
    事故を踏んだ(2026-07-26)。Viteはファイル名に内容ハッシュを付けるので、
    HTMLさえ最新なら参照されるJS/CSSは必ず一致する——罠自体が構造的に消えた。
    """
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith("index.html"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/assets"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
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


async def _watch_forever() -> None:
    """シグナリング監視を、死んでも起こし直しながら回し続ける。

    監視が止まる=電話が鳴らなくなる、なので「ログを残して終わり」にしない。
    かつてMinIOの資格情報事故で監視が静かに死に、実架電を取り逃した。
    """
    while True:
        try:
            await _watch_signaling()
            log.error("シグナリング監視が終了した — 15秒後に再開する")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("シグナリング監視が落ちた — 15秒後に再開する")
        await asyncio.sleep(15)


async def _watch_signaling() -> None:
    """コールフローからの呼設定を受け取り、呼ごとに受信を始める。"""
    log.info("シグナリング監視を開始")
    async for ev in signaling.poll_call_events():
        # 呼1件の異常でループを殺さない。1呼の失敗は1呼で閉じる
        try:
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
                instance_arn=ev.instance_arn,
                record_audio=True,
                save_transcript=True,
            )
            _start_session(session, sources.stream_from_kvs(ev.stream_arn, ev.start_fragment))
        except Exception:
            log.exception("呼イベントの処理に失敗(監視は続行): %r", dict(ev))


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
async def api_replay(file: str = "call.mkv", speed: float = 1.0) -> dict:
    """開発用: recordings/ 直下のMKVを流して、架電せずに画面まで通しで試す。

    連打で同時セッションが積み上がらないよう、リプレイは同時1本まで(実通話は無制限)。
    """
    running = [
        cid for cid, t in _sessions.items()
        if cid.startswith("replay-") and not t.done()
    ]
    if running:
        raise HTTPException(409, "リプレイが既に実行中です。終了を待ってください")
    path = RECORDINGS_DIR / file
    if path.parent != RECORDINGS_DIR:
        raise HTTPException(400, "fileはrecordings/直下のみ")
    if not path.exists():
        raise HTTPException(404, f"{path.name} がありません")

    new_id = f"replay-{uuid.uuid4().hex[:8]}"
    session = CallSession(hub, contact_id=new_id, label=f"replay:{file}")
    _start_session(session, sources.replay_file(path, speed))
    return {"status": "started", "contact_id": new_id, "source": path.name, "speed": speed}


@app.post("/api/reprocess/{contact_id}")
async def api_reprocess(contact_id: str, speed: float = 2.0) -> dict:
    """過去の呼を**同じCallIDのまま**再文字起こしする。履歴は増えない。

    録音MKVをパイプラインに流し直し、終了時に記録を上書き保存する。
    """
    if contact_id in _sessions and not _sessions[contact_id].done():
        raise HTTPException(409, "この呼は処理中です")
    try:
        data = storage.get_recording(contact_id)
    except ValueError:
        raise HTTPException(400, "不正なcontact_id")
    if data is None:
        raise HTTPException(404, "この呼の録音がありません")

    # 元の呼のメタ(発信者番号・開始時刻)を引き継ぐ
    old = hub.get_record(contact_id)
    meta = old.meta() if old else (history.load_record(contact_id) or {})
    session = CallSession(
        hub,
        contact_id=contact_id,
        label=meta.get("label") or "reprocess",
        customer_number=meta.get("customer_number"),
        instance_arn=meta.get("instance_arn"),
        save_transcript=True,
    )
    # 再処理でも「いつの通話か」は動かさない
    if meta.get("started_at"):
        session.record.started_at = meta["started_at"]
    session.record.fixed_ended_at = meta.get("ended_at")
    _start_session(session, sources.replay_bytes(data, speed, contact_id))
    return {"status": "started", "contact_id": contact_id, "speed": speed}


@app.get("/api/history/{contact_id}/card.json")
def api_card(contact_id: str) -> Response:
    """通話カードをJSONで返す。外部システムへの受け渡し口。

    画面で見るだけならhistoryに含まれているが、保存・連携のために
    ファイルとして落とせる形も用意しておく。
    """
    call = hub.get_record(contact_id)
    rec = call.as_dict() if call is not None else history.load_record(contact_id)
    if rec is None:
        raise HTTPException(404, f"呼 {contact_id} の記録がありません")
    if not rec.get("card"):
        raise HTTPException(404, "この呼の通話カードはまだありません")
    body = {
        "contact_id": contact_id,
        "customer_number": rec.get("customer_number"),
        "started_at": rec.get("started_at"),
        "ended_at": rec.get("ended_at"),
        "max_anger": rec.get("max_anger"),
        "max_voice_anger": rec.get("max_voice_anger"),
        **rec["card"],
    }
    return Response(
        json.dumps(body, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="card-{contact_id}.json"'},
    )


@app.get("/api/recordings/{contact_id}.wav")
def api_recording_wav(
    contact_id: str, start_ms: int | None = None, end_ms: int | None = None
) -> Response:
    """録音を左=相手/右=こちらのステレオWAVで返す(ブラウザ再生用)。

    start_ms/end_ms を渡すとその区間だけを切り出す。発話ごとの頭出し再生に使う。
    """
    try:
        data = storage.get_recording(contact_id)
    except ValueError:
        raise HTTPException(400, "不正なcontact_id")
    if data is None:
        raise HTTPException(404, "この呼の録音がありません")
    try:
        wav = audio.mkv_to_stereo_wav(data, start_ms, end_ms)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return Response(wav, media_type="audio/wav")


@app.get("/api/recording-files")
def api_recording_files() -> list[dict]:
    """開発用リプレイに使える recordings/ 直下のMKV一覧。"""
    if not RECORDINGS_DIR.exists():
        return []
    return [
        {"file": p.name, "size": p.stat().st_size}
        for p in sorted(RECORDINGS_DIR.glob("*.mkv"))
    ]


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
        # 設定値ではなく実際に監視タスクが生きているかを返す
        "watching": bool(_watcher and not _watcher.done()),
        "watch_configured": WATCH_CALLS,
        "active_calls": len(_sessions),
        "history_backend": history.backend(),
        "recording_backend": "s3" if storage.enabled() else "files",
        "ts": time.time(),
    }


@app.get("/")
def index() -> FileResponse:
    if not (FRONTEND_DIR / "index.html").exists():
        raise HTTPException(503, "フロントが未ビルドです。frontend/ で `npm run build` を実行してください")
    return FileResponse(FRONTEND_DIR / "index.html")


# ビルド成果物が無くてもバックエンド単独で起動できるようにする。
# CI(pytest)やAPIだけ叩く用途では dist/ は存在しない
if (FRONTEND_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
else:
    log.warning("frontend/dist が無いため画面は配信しない(APIのみ): %s", FRONTEND_DIR)
