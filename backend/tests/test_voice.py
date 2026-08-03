"""声のトーン判定の周辺ロジック。APIには出ない(judge_voice本体は呼ばない)。"""

from __future__ import annotations

import numpy as np

import numpy as _np

import voice
from voice import VoiceBuffer, VoiceWatcher, _parse, collect_spans, voiced_seconds


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
    assert b.take_recent(10.0).size == 8000 * 2
    assert b.start_sample == 8000 * 3  # 先頭3秒ぶんは捨てられている


def test_voiced_seconds_counts_content_not_length():
    """窓の長さではなく中身で測ること。

    12秒の窓に声が0.3秒しか無い状態で投げると「音声が聞こえない」と返される
    だけで課金される、という実測に基づく足切りの土台。
    """
    x = _np.concatenate([
        _np.frombuffer(_silence(9.0), dtype="<i2"),
        _np.frombuffer(_tone(1.0), dtype="<i2"),
        _np.frombuffer(_silence(1.0), dtype="<i2"),
    ])
    v = voiced_seconds(x)
    assert 0.8 < v < 1.2, f"有声秒数がずれている: {v}"
    assert voiced_seconds(_np.frombuffer(_silence(10.0), dtype="<i2")) == 0.0


def test_extract_ms_uses_absolute_timeline():
    """発話区間の座標は通話開始からの絶対msで、輪が回っても正しく切り出せること。"""
    b = VoiceBuffer(seconds=5.0)
    b.add(_silence(10.0))       # 0-10秒: 無音
    b.add(_tone(2.0))           # 10-12秒: 声
    b.add(_silence(1.0))        # 12-13秒: 無音(保持は8-13秒ぶん)
    seg = b.extract_ms(10_000, 12_000, pad_ms=0)
    assert seg.size == 8000 * 2
    assert voiced_seconds(seg) > 1.8  # 切り出したのは声の区間そのもの

    # 保持窓より古い区間は、残っている部分だけが返る(黙って全部は返さない)
    old = b.extract_ms(0, 2_000, pad_ms=0)
    assert old.size == 0


def test_collect_spans_gathers_recent_customer_utterances():
    def m(speaker, a, b, final=True):
        return {"speaker": speaker, "final": final,
                "audio_start_ms": a, "audio_end_ms": b, "text": "x"}

    messages = [
        m("customer", 0, 3000),        # 古い。目標長に達したら含まれない
        m("agent", 3000, 4000),        # 相手側ではない
        m("customer", 5000, 9000),
        m("customer", None, None),     # 区間なし(スキップ)
        m("customer", 10000, 15000),
        m("customer", 16000, 16000, final=False),  # 未確定(スキップ)
    ]
    spans = collect_spans(messages, target_sec=8.0)
    # 新しい方から 5秒+4秒=9秒 ≥ 8秒 で打ち切り。時系列順で返る
    assert spans == [(5000, 9000), (10000, 15000)]
    assert collect_spans([]) == []


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


def test_material_prefers_spans_and_falls_back():
    """材料づくり: 発話区間があれば積み、無ければ生窓、無音なら空。"""
    async def emit(msg):
        pass

    w = VoiceWatcher("c1", emit=emit)
    w.buffer.add(_silence(2.0))
    w.buffer.add(_tone(6.0))    # 2-8秒: 声
    w.buffer.add(_silence(2.0))

    msgs = [{"speaker": "customer", "final": True, "text": "x",
             "audio_start_ms": 2000, "audio_end_ms": 8000}]
    pcm, source = w._material(msgs)
    assert source == "spans"
    assert pcm.size >= 8000 * 6  # 6秒の発話+余白

    # 区間情報が無いSTT構成 → 生窓に落ちる
    pcm, source = w._material([{"speaker": "customer", "final": True, "text": "x"}])
    assert source == "window"
    assert pcm.size > 0

    # ほぼ無音 → 投げない
    quiet = VoiceWatcher("c2", emit=emit)
    quiet.buffer.add(_silence(12.0))
    pcm, source = quiet._material([])
    assert source == "silent" and pcm.size == 0
