"""音声変換まわり。

- Resampler: 電話帯域(8kHz)の生PCMを Realtime API が要求する24kHzへ変換する。
  audioop は Python 3.13 で標準ライブラリから外れたため numpy で自前補間する。
  チャンク境界でプツッと鳴らないよう、直前の最終サンプルを持ち越して補間する。
- mkv_to_stereo_wav: 保存した録音(MKV)をブラウザで再生できるWAVにする。
  MKV+生L16はブラウザが再生できない(CodecID詐称問題)ため、サーバー側で変換する。
"""

from __future__ import annotations

import io
import wave

import numpy as np

from config import SOURCE_RATE, SPEAKER_BY_TRACK_NAME, TARGET_RATE
from mkv import MkvStreamParser

_RATIO = TARGET_RATE // SOURCE_RATE


class Resampler:
    """8kHz → 24kHz の線形補間アップサンプラ(話者ごとに1つ持つ)。"""

    def __init__(self) -> None:
        self._tail = np.zeros(1, dtype=np.int16)

    def process(self, pcm: bytes) -> bytes:
        if not pcm:
            return b""
        samples = np.frombuffer(pcm, dtype="<i2")
        if samples.size == 0:
            return b""

        # 前チャンクの最後を先頭に足して、境界をまたぐ補間を連続させる
        joined = np.concatenate([self._tail, samples])
        self._tail = samples[-1:].copy()

        src_x = np.arange(joined.size, dtype=np.float64)
        # 先頭の持ち越し1サンプル分は出力から捨てるので、その分だけ後ろにずらす
        out_x = np.arange(1 * _RATIO, joined.size * _RATIO, dtype=np.float64) / _RATIO
        out = np.interp(out_x, src_x, joined.astype(np.float64))
        return np.rint(out).astype("<i2").tobytes()


def mkv_to_stereo_wav(mkv_bytes: bytes) -> bytes:
    """録音MKVを、左=相手(FROM_CUSTOMER)/右=こちら(TO_CUSTOMER)のステレオWAVにする。

    左右に振ることで、聴くだけで話者分離の状態が分かる。
    """
    parser = MkvStreamParser()
    raw: dict[int, bytearray] = {}
    for block in parser.feed(mkv_bytes):
        raw.setdefault(block.track, bytearray()).extend(block.pcm)

    by_speaker: dict[str, np.ndarray] = {}
    for track, pcm in raw.items():
        speaker = SPEAKER_BY_TRACK_NAME.get(parser.track_names.get(track, ""))
        if speaker:
            by_speaker[speaker] = np.frombuffer(bytes(pcm), dtype="<i2")

    if not by_speaker:
        raise ValueError("音声トラックが見つかりません")

    n = max(a.size for a in by_speaker.values())

    def pad(a: np.ndarray) -> np.ndarray:
        return np.pad(a, (0, n - a.size))

    left = pad(by_speaker.get("customer", np.zeros(0, dtype="<i2")))
    right = pad(by_speaker.get("agent", np.zeros(0, dtype="<i2")))
    stereo = np.empty(n * 2, dtype="<i2")
    stereo[0::2] = left
    stereo[1::2] = right

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SOURCE_RATE)
        w.writeframes(stereo.tobytes())
    return buf.getvalue()
