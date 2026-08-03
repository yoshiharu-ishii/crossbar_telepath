"""音声変換の検証。リサンプラの連続性と、録音→WAV変換。"""

from __future__ import annotations

import io
import wave

import numpy as np

from audio import Resampler, mkv_to_stereo_wav
from make_test_call import build_mkv


def _tone(freq: float, sec: float, rate: int = 8000) -> np.ndarray:
    t = np.arange(int(rate * sec)) / rate
    return (np.sin(2 * np.pi * freq * t) * 8000).astype("<i2")


def test_resampler_ratio():
    out = Resampler().process(_tone(440, 1.0).tobytes())
    assert len(out) == 8000 * 3 * 2  # 8k→24k, 16bit


def test_resampler_chunk_boundary_continuity():
    """チャンクを跨いでも波形が滑らかであること(境界のプツッ音の回帰テスト)。

    一括変換と分割変換の差ではなく、出力波形の隣接サンプル差(ジャンプ)を見る。
    境界処理を誤ると 20ms ごとに不連続が入り、最大ジャンプが跳ね上がる。
    """
    pcm = _tone(440, 1.0).tobytes()
    r = Resampler()
    step = 8000 * 2 * 20 // 1000  # 20msずつ(実機と同じ粒度)
    chunks = b"".join(r.process(pcm[i : i + step]) for i in range(0, len(pcm), step))
    x = np.frombuffer(chunks, dtype="<i2").astype(np.float64)
    max_jump = np.abs(np.diff(x)).max()
    # 440Hz/24kHzの正弦波の理論最大傾斜は amp*2π*440/24000 ≈ amp*0.115
    assert max_jump < 8000 * 0.115 * 1.5, f"境界に不連続がある(max_jump={max_jump:.0f})"
    # さらに強く: 分割変換は一括変換とバイト一致であること
    whole = Resampler().process(pcm)
    assert chunks == whole, "チャンクの切り方で出力が変わっている"


def test_mkv_to_stereo_wav_layout():
    """左=相手 / 右=こちら、8kHzステレオで出ること。"""
    data = build_mkv(customer=_tone(440, 0.5), agent=_tone(880, 0.5))
    with wave.open(io.BytesIO(mkv_to_stereo_wav(data)), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (2, 8000, 2)
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    left, right = frames[0::2], frames[1::2]

    def peak(x):
        spec = np.abs(np.fft.rfft(x.astype(np.float64)))
        return float(np.fft.rfftfreq(x.size, d=1 / 8000)[int(spec.argmax())])

    assert abs(peak(left) - 440) < 5   # 左=customer
    assert abs(peak(right) - 880) < 5  # 右=agent


def test_mkv_to_stereo_wav_segment_cut():
    """start_ms/end_ms で発話区間だけを切り出せること(頭出し再生の土台)。"""
    data = build_mkv(customer=_tone(440, 2.0), agent=_tone(880, 2.0))
    full = mkv_to_stereo_wav(data)
    seg = mkv_to_stereo_wav(data, start_ms=500, end_ms=1000)
    with wave.open(io.BytesIO(seg), "rb") as w:
        sec = w.getnframes() / w.getframerate()
    # 0.5秒+前後の余白(0.3秒×2)
    assert 0.9 < sec < 1.3
    assert len(seg) < len(full)
