"""声のトーン判定の周辺ロジック。APIには出ない(judge_voice本体は呼ばない)。"""

from __future__ import annotations

import numpy as np

import voice
from voice import VoiceBuffer, VoiceWatcher, _parse


# ---- _parse: gpt-audio系は response_format 非対応のため、応答の救出が要る ----


def test_parse_clean_json():
    assert _parse('{"anger": 45, "tone": "硬い"}') == {"anger": 45, "tone": "硬い"}


def test_parse_json_with_surrounding_prose():
    # モデルが前後に文を付けてくることがある
    got = _parse('了解しました。{"anger": 70, "tone": "怒鳴っている"}以上です。')
    assert got == {"anger": 70, "tone": "怒鳴っている"}


def test_parse_refusal_returns_none():
    # 「音声をお聞かせください」型の先送り応答はNoneになる(それをどう減らすかは
    # プロンプト側の仕事。実測の経緯は voice.py のコメント参照)
    assert _parse("申し訳ありませんが、音声をお聞かせください。") is None


# ---- VoiceBuffer: 輪の上限と、中身(有声秒数)での足切り ----


def _tone(sec: float, amp: int = 8000) -> bytes:
    t = np.arange(int(8000 * sec)) / 8000
    return (np.sin(2 * np.pi * 440 * t) * amp).astype("<i2").tobytes()


def _silence(sec: float) -> bytes:
    return np.zeros(int(8000 * sec), dtype="<i2").tobytes()


def test_buffer_keeps_only_recent_window():
    b = VoiceBuffer(seconds=2.0)
    b.add(_tone(5.0))
    assert b.take().size == 8000 * 2


def test_voiced_seconds_counts_content_not_length():
    """窓の長さではなく中身で測ること。

    12秒の窓に声が0.3秒しか無い状態で投げると「音声が聞こえない」と返される
    だけで課金される、という実測に基づく足切りの土台。
    """
    b = VoiceBuffer(seconds=12.0)
    b.add(_silence(9.0))
    b.add(_tone(1.0))
    b.add(_silence(1.0))
    v = b.voiced_seconds()
    assert 0.8 < v < 1.2, f"有声秒数がずれている: {v}"

    quiet = VoiceBuffer(seconds=12.0)
    quiet.add(_silence(10.0))
    assert quiet.voiced_seconds() == 0.0


# ---- VoiceWatcher: トリガ条件 ----


def test_should_judge_respects_mode_and_trigger(monkeypatch):
    async def emit(msg):
        pass

    w = VoiceWatcher("c1", emit=emit)

    monkeypatch.setattr(voice, "VOICE_JUDGE_MODE", "off")
    assert not w.should_judge(90)

    monkeypatch.setattr(voice, "VOICE_JUDGE_MODE", "auto")
    monkeypatch.setattr(voice, "VOICE_JUDGE_INTERVAL_SEC", 0.0)
    assert not w.should_judge(voice.VOICE_TRIGGER_SCORE - 1)  # 閾値未満は聴かない
    assert w.should_judge(voice.VOICE_TRIGGER_SCORE)

    monkeypatch.setattr(voice, "VOICE_JUDGE_MODE", "always")
    assert w.should_judge(0)  # 検証用モードはスコアに関係なく聴く

    w._busy = True
    assert not w.should_judge(100)  # 実行中は重ねない
