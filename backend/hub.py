"""呼単位のセッション管理とブラウザへの配信。

ここが「プログラマブル交換機(INのSCP)」の中心。シグナリングで呼を identify し、
通話路(KVS)から届いたMKVをパースして話者ごとのRealtimeセッションへ振り分け、
結果を接続中のブラウザ全員へ流す。すべてのメッセージは contact_id を持ち、
どの呼の出来事かが常に確定している。

通話が終わると、呼の記録(CDR+確定発言)を history に書き、
実通話なら受信した生MKVも録音として残す。PH3の心理分析もこの器に載る。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import WebSocket

import card
import emotion
import history
import storage
import voice
from config import CARD_ENABLED, MAX_RECENT_CALLS, SPEAKER_BY_TRACK_NAME
from mkv import MkvStreamParser
from transcribe import Transcriber

log = logging.getLogger(__name__)


@dataclass
class CallRecord:
    """1つの呼の記録。画面の再現と永続化に必要なものだけ持つ。"""

    contact_id: str
    label: str
    customer_number: str | None = None
    instance_arn: str | None = None
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    messages: list[dict] = field(default_factory=list)
    # 過去の呼を再処理するときは、実際に通話が終わった時刻を保つ
    # (現在時刻で上書きすると通話時間が何日にも化ける)
    fixed_ended_at: float | None = None
    # 通話カード(切断後に1回だけ生成)。外部システムへの受け渡し口を兼ねる
    card: dict | None = None

    @property
    def max_voice_anger(self) -> int | None:
        """声のトーンから見た最大値。テキストと別に持つ(食い違いに意味があるため)。"""
        scores = [m["voice_score"] for m in self.messages if m.get("voice_score") is not None]
        return max(scores) if scores else None

    @property
    def max_anger(self) -> int | None:
        """この呼で最も高かった怒り度。履歴から「揉めた通話」を探すための値。

        **テキストと声の高い方を採る(発話ごとにmax)。** 実測で声はテキストを
        先行する(2026-08-03)ため、片方だけ見ると揉めた通話を取り逃す。
        """
        scores = [
            max(m.get("anger_score") or 0, m.get("voice_score") or 0)
            for m in self.messages
            if m.get("anger_score") is not None or m.get("voice_score") is not None
        ]
        return max(scores) if scores else None

    def meta(self) -> dict:
        return {
            "contact_id": self.contact_id,
            "label": self.label,
            "customer_number": self.customer_number,
            "instance_arn": self.instance_arn,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "message_count": len(self.messages),
            "max_anger": self.max_anger,
            "max_voice_anger": self.max_voice_anger,
            "summary": (self.card or {}).get("summary"),
            "card": self.card,
            "has_recording": storage.has_recording(self.contact_id),
            "live": self.ended_at is None,
        }

    def as_dict(self) -> dict:
        return {**self.meta(), "messages": self.messages}


class Hub:
    """ブラウザ接続の集合と、処理中の呼。"""

    # ディスクに書かない呼(リプレイ)も、セッション中は選択できるよう残す数
    MAX_RECENT = MAX_RECENT_CALLS

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self.active: dict[str, CallRecord] = {}
        self.recent: OrderedDict[str, CallRecord] = OrderedDict()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, msg: dict) -> None:
        msg.setdefault("ts", time.time())
        call = self.active.get(msg.get("contact_id", ""))
        if call is not None and msg.get("type") == "transcript" and msg.get("final"):
            call.messages.append(msg)

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
        self.active[record.contact_id] = record
        await self.broadcast({"type": "call_started", **record.meta()})

    async def call_ended(self, contact_id: str, *, persist: bool) -> None:
        call = self.active.pop(contact_id, None)
        if call is None:
            return
        call.ended_at = call.fixed_ended_at or time.time()
        if persist:
            try:
                # DBやS3への書き込みでイベントループを止めない
                await asyncio.to_thread(history.save_record, call.as_dict())
            except Exception:
                log.exception("呼記録の保存に失敗: %s", contact_id)
        self.recent[contact_id] = call
        while len(self.recent) > self.MAX_RECENT:
            self.recent.popitem(last=False)
        await self.broadcast({"type": "call_ended", **call.meta()})

    def get_record(self, contact_id: str) -> CallRecord | None:
        """処理中または終了直後の呼(メモリ上のもの)。"""
        return self.active.get(contact_id) or self.recent.get(contact_id)


class CallSession:
    """1つの呼の処理。MKVをパースし、話者別のTranscriberへ配る。

    - record_audio: 受信した生バイト列を録音としてteeする(実通話)
    - save_transcript: 終了時に呼の記録をディスクへ書く(実通話と再文字起こし)
    開発用のファイルリプレイはどちらも行わない。
    """

    def __init__(
        self,
        hub: Hub,
        contact_id: str,
        label: str,
        customer_number: str | None = None,
        instance_arn: str | None = None,
        record_audio: bool = False,
        save_transcript: bool = False,
    ) -> None:
        self.hub = hub
        self.contact_id = contact_id
        self.record_audio = record_audio
        self.save_transcript = save_transcript
        self.record = CallRecord(
            contact_id=contact_id,
            label=label,
            customer_number=customer_number,
            instance_arn=instance_arn,
        )
        self._parser = MkvStreamParser()
        self._transcribers: dict[str, Transcriber] = {}
        # _emit を渡す。contact_id はそこで必ず添えられる
        self._anger = emotion.AngerWatcher(contact_id, self._emit)
        self._voice = voice.VoiceWatcher(contact_id, self._emit)
        self._judging: set[asyncio.Task] = set()

    async def run(self, source: AsyncIterator[bytes]) -> None:
        await self.hub.call_started(self.record)
        log.info("call started: %s (%s)", self.contact_id, self.record.label)
        # 通話中はローカルの一時ファイルへ書き、終了時にまとめて保存する
        # (Fargateではローカルディスクが揮発するため、置き場はstorageに委ねる)
        tmp_path = None
        rec_file = None
        if self.record_audio:
            fd, name = tempfile.mkstemp(prefix=f"{self.contact_id}-", suffix=".mkv")
            tmp_path = Path(name)
            rec_file = os.fdopen(fd, "wb")
        try:
            async for data in source:
                if rec_file:
                    rec_file.write(data)
                for block in self._parser.feed(data):
                    await self._dispatch(block)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("call session failed: %s", self.contact_id)
        finally:
            if rec_file:
                rec_file.close()
            if tmp_path:
                try:
                    await asyncio.to_thread(
                        storage.put_recording, self.contact_id, tmp_path.read_bytes()
                    )
                except Exception:
                    log.exception("録音の保存に失敗: %s", self.contact_id)
                finally:
                    tmp_path.unlink(missing_ok=True)
            await self._close_all()
            # 判定の結果を取りこぼさずに記録へ残す
            if self._judging:
                await asyncio.gather(*self._judging, return_exceptions=True)
            if CARD_ENABLED:
                self.record.card = await card.make_card(self.record.messages)
            await self.hub.call_ended(self.contact_id, persist=self.save_transcript)
            log.info("call ended: %s", self.contact_id)

    async def _emit(self, msg: dict) -> None:
        msg["contact_id"] = self.contact_id
        await self.hub.broadcast(msg)
        # 文字起こしの流れを止めないよう、判定は別タスクで走らせる
        if msg.get("type") == "transcript" and self._anger.should_judge(msg):
            self._spawn(self._anger.run(self.record.messages, msg))
        # テキストが高いときだけ声を聴く。判定対象の発話に結果を相乗りさせる
        if msg.get("type") == "emotion" and self._voice.should_judge(msg.get("score", 0)):
            target = self._find_message(msg.get("item_id"))
            if target is not None:
                self._spawn(self._voice.run(self.record.messages, target))

    def _spawn(self, coro) -> None:
        """判定は別タスクで走らせる。文字起こしの流れを止めないため。"""
        task = asyncio.create_task(coro)
        self._judging.add(task)
        task.add_done_callback(self._judging.discard)

    def _find_message(self, item_id: str | None) -> dict | None:
        for m in reversed(self.record.messages):
            if m.get("item_id") == item_id:
                return m
        return None

    async def _dispatch(self, block) -> None:
        track_name = self._parser.track_names.get(block.track)
        speaker = SPEAKER_BY_TRACK_NAME.get(track_name or "")
        if speaker is None:
            log.warning("unknown track %s (%s), skipped", block.track, track_name)
            return
        if speaker == "customer" and self._voice.enabled:
            self._voice.buffer.add(block.pcm)
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
