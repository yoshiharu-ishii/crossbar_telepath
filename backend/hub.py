"""呼単位のセッション管理とブラウザへの配信。

ここが「プログラマブル交換機(INのSCP)」の中心。シグナリングで呼を identify し、
通話路(KVS)から届いたMKVをパースして話者ごとのRealtimeセッションへ振り分け、
結果を接続中のブラウザ全員へ流す。すべてのメッセージは contact_id を持ち、
どの呼の出来事かが常に確定している。PH3の心理分析もこの器に載る。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi import WebSocket

from config import SPEAKER_BY_TRACK_NAME
from mkv import MkvStreamParser
from transcribe import Transcriber

log = logging.getLogger(__name__)

# 画面に残す呼の数(古い呼から捨てる)
MAX_CALLS = 5
# 1呼あたり保持する確定発言の数
MAX_MESSAGES = 200


@dataclass
class CallRecord:
    """1つの呼の見え方。ブラウザに再現するのに必要なものだけ持つ。"""

    contact_id: str
    label: str
    customer_number: str | None = None
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    messages: list[dict] = field(default_factory=list)

    def as_started(self) -> dict:
        return {
            "type": "call_started",
            "contact_id": self.contact_id,
            "label": self.label,
            "customer_number": self.customer_number,
            "ts": self.started_at,
        }

    def as_ended(self) -> dict:
        return {"type": "call_ended", "contact_id": self.contact_id, "ts": self.ended_at}


class Hub:
    """ブラウザ接続の集合と、直近の呼の記録。"""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._calls: OrderedDict[str, CallRecord] = OrderedDict()

    # ---- ブラウザ側 ----

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        # 後から開いた画面でも、いまの呼と直近の呼が見えるようにする
        for call in self._calls.values():
            await self._send(ws, call.as_started())
            for msg in call.messages:
                await self._send(ws, msg)
            if call.ended_at:
                await self._send(ws, call.as_ended())

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    @staticmethod
    async def _send(ws: WebSocket, msg: dict) -> None:
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps(msg, ensure_ascii=False))

    async def broadcast(self, msg: dict) -> None:
        msg.setdefault("ts", time.time())
        call = self._calls.get(msg.get("contact_id", ""))
        if call is not None and msg.get("type") == "transcript" and msg.get("final"):
            call.messages.append(msg)
            del call.messages[:-MAX_MESSAGES]

        payload = json.dumps(msg, ensure_ascii=False)
        dead = []
        for ws in self._clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    # ---- 呼の出入り ----

    async def call_started(self, record: CallRecord) -> None:
        self._calls[record.contact_id] = record
        while len(self._calls) > MAX_CALLS:
            self._calls.popitem(last=False)
        await self.broadcast(record.as_started())

    async def call_ended(self, contact_id: str) -> None:
        call = self._calls.get(contact_id)
        if call is None:
            return
        call.ended_at = time.time()
        await self.broadcast(call.as_ended())

    def active_calls(self) -> list[dict]:
        return [c.as_started() for c in self._calls.values() if c.ended_at is None]


class CallSession:
    """1つの呼の処理。MKVをパースし、話者別のTranscriberへ配る。"""

    def __init__(
        self,
        hub: Hub,
        contact_id: str,
        label: str,
        customer_number: str | None = None,
    ) -> None:
        self.hub = hub
        self.contact_id = contact_id
        self.record = CallRecord(contact_id=contact_id, label=label, customer_number=customer_number)
        self._parser = MkvStreamParser()
        self._transcribers: dict[str, Transcriber] = {}

    async def run(self, source: AsyncIterator[bytes]) -> None:
        await self.hub.call_started(self.record)
        log.info("call started: %s (%s)", self.contact_id, self.record.label)
        try:
            async for data in source:
                for block in self._parser.feed(data):
                    await self._dispatch(block)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("call session failed: %s", self.contact_id)
        finally:
            await self._close_all()
            await self.hub.call_ended(self.contact_id)
            log.info("call ended: %s", self.contact_id)

    async def _emit(self, msg: dict) -> None:
        """どの呼の出来事かを必ず添えて流す。"""
        msg["contact_id"] = self.contact_id
        await self.hub.broadcast(msg)

    async def _dispatch(self, block) -> None:
        track_name = self._parser.track_names.get(block.track)
        speaker = SPEAKER_BY_TRACK_NAME.get(track_name or "")
        if speaker is None:
            log.warning("unknown track %s (%s), skipped", block.track, track_name)
            return
        tr = self._transcribers.get(speaker)
        if tr is None:
            tr = Transcriber(speaker, self._emit)
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
