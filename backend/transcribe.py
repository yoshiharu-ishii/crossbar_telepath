"""話者1人ぶんの文字起こしセッション(OpenAI Realtime API)。

Realtime APIの transcription セッションに音声を流し込み、返ってきた
delta / completed をそのまま上位へ渡す。server VADが発話の切れ目を判断するので
こちら側で無音検出はしない。PH3の心理分析も同じWebSocket配管に相乗りさせる。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

from audio import Resampler
from config import (
    AUDIO_FLUSH_MS,
    REALTIME_URL,
    SAMPLE_WIDTH,
    SOURCE_RATE,
    TARGET_RATE,
    TRANSCRIBE_LANGUAGE,
    TRANSCRIBE_MODEL,
    VAD_SILENCE_MS,
    get_api_key,
)

log = logging.getLogger(__name__)

# 送信前に貯めるバイト数(8kHz/16bitでAUDIO_FLUSH_MSぶん)
_FLUSH_BYTES = SOURCE_RATE * SAMPLE_WIDTH * AUDIO_FLUSH_MS // 1000


class Transcriber:
    """1話者ぶんのRealtime接続。send()で音声を入れると on_event が呼ばれる。"""

    def __init__(self, speaker: str, on_event: Callable[[dict], Awaitable[None]]) -> None:
        self.speaker = speaker
        self._on_event = on_event
        self._resampler = Resampler()
        self._pending = bytearray()
        self._ws: websockets.ClientConnection | None = None
        self._reader: asyncio.Task | None = None

    async def start(self) -> None:
        key = get_api_key()
        if not key:
            raise RuntimeError("APIキーが .env に設定されていません")
        self._ws = await websockets.connect(
            REALTIME_URL, additional_headers={"Authorization": f"Bearer {key}"}
        )
        await self._ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": TARGET_RATE},
                        "transcription": {
                            "model": TRANSCRIBE_MODEL,
                            "language": TRANSCRIBE_LANGUAGE,
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "silence_duration_ms": VAD_SILENCE_MS,
                        },
                    }
                },
            },
        }))
        self._reader = asyncio.create_task(self._read_loop())
        log.info("transcriber started: %s", self.speaker)

    async def send(self, pcm_8k: bytes) -> None:
        """電話帯域のPCMを投入する。一定量たまったらまとめて送信する。"""
        self._pending.extend(pcm_8k)
        if len(self._pending) < _FLUSH_BYTES:
            return
        chunk = bytes(self._pending)
        self._pending.clear()
        await self._send_now(chunk)

    async def flush(self) -> None:
        if self._pending:
            chunk = bytes(self._pending)
            self._pending.clear()
            await self._send_now(chunk)

    async def _send_now(self, pcm_8k: bytes) -> None:
        if self._ws is None:
            return
        audio = self._resampler.process(pcm_8k)
        try:
            await self._ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio).decode(),
            }))
        except websockets.ConnectionClosed:
            log.warning("realtime connection closed while sending: %s", self.speaker)

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                ev = json.loads(raw)
                out = self._translate(ev)
                if out:
                    await self._on_event(out)
        except websockets.ConnectionClosed:
            log.info("realtime connection closed: %s", self.speaker)
        except Exception:
            log.exception("transcriber read loop failed: %s", self.speaker)

    def _translate(self, ev: dict) -> dict | None:
        """Realtime APIのイベントを、画面がそのまま使える形に翻訳する。"""
        kind = ev.get("type", "")
        if kind == "conversation.item.input_audio_transcription.delta":
            return {
                "type": "transcript",
                "speaker": self.speaker,
                "item_id": ev.get("item_id"),
                "delta": ev.get("delta", ""),
                "final": False,
            }
        if kind == "conversation.item.input_audio_transcription.completed":
            return {
                "type": "transcript",
                "speaker": self.speaker,
                "item_id": ev.get("item_id"),
                "text": ev.get("transcript", ""),
                "final": True,
            }
        if kind in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"):
            return {
                "type": "speech",
                "speaker": self.speaker,
                "active": kind.endswith("started"),
            }
        if kind == "error":
            log.error("realtime error (%s): %s", self.speaker, ev)
            return {"type": "error", "speaker": self.speaker, "message": str(ev.get("error"))}
        return None

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self._ws:
            await self._ws.close()
        self._ws = None
