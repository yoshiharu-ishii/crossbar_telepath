"""通話セッションの管理とブラウザへの配信。

ここが「プログラマブル交換機(INのSCP)」の中心。KVSから届いたMKVをパースし、
話者ごとのRealtimeセッションへ振り分け、結果を接続中のブラウザ全員へ流す。
PH3の心理分析も、このハブに新しいイベント種別を足す形で載る。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import WebSocket

from config import SPEAKER_BY_TRACK_NAME
from mkv import MkvStreamParser
from transcribe import Transcriber

log = logging.getLogger(__name__)


class Hub:
    """ブラウザ接続の集合。通話の状態と直近の発言を保持して新規接続に配る。"""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._history: list[dict] = []
        self.state: dict = {"type": "call_state", "status": "idle", "label": None}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        await ws.send_text(json.dumps(self.state, ensure_ascii=False))
        for msg in self._history[-50:]:
            await ws.send_text(json.dumps(msg, ensure_ascii=False))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, msg: dict) -> None:
        msg.setdefault("ts", time.time())
        if msg.get("type") == "call_state":
            self.state = msg
            if msg.get("status") == "active":
                self._history.clear()
        elif msg.get("type") == "transcript" and msg.get("final"):
            self._history.append(msg)

        payload = json.dumps(msg, ensure_ascii=False)
        dead = []
        for ws in self._clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)


class CallSession:
    """1通話ぶんの処理。MKVをパースし、話者別のTranscriberへ配る。"""

    def __init__(self, hub: Hub, label: str) -> None:
        self.hub = hub
        self.label = label
        self._parser = MkvStreamParser()
        self._transcribers: dict[str, Transcriber] = {}

    async def run(self, source: AsyncIterator[bytes]) -> None:
        await self.hub.broadcast({
            "type": "call_state", "status": "active", "label": self.label,
        })
        try:
            async for data in source:
                for block in self._parser.feed(data):
                    await self._dispatch(block)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("call session failed: %s", self.label)
        finally:
            await self._close_all()
            await self.hub.broadcast({
                "type": "call_state", "status": "idle", "label": self.label,
            })

    async def _dispatch(self, block) -> None:
        track_name = self._parser.track_names.get(block.track)
        speaker = SPEAKER_BY_TRACK_NAME.get(track_name or "")
        if speaker is None:
            log.warning("unknown track %s (%s), skipped", block.track, track_name)
            return
        tr = self._transcribers.get(speaker)
        if tr is None:
            tr = Transcriber(speaker, self.hub.broadcast)
            await tr.start()
            self._transcribers[speaker] = tr
        await tr.send(block.pcm)

    async def _close_all(self) -> None:
        for tr in self._transcribers.values():
            with contextlib.suppress(Exception):
                await tr.flush()
        # 最後の発話の文字起こしが返るまで少しだけ待つ
        await asyncio.sleep(2.0)
        for tr in self._transcribers.values():
            with contextlib.suppress(Exception):
                await tr.close()
        self._transcribers.clear()
