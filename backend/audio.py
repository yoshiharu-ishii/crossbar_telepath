"""電話帯域(8kHz)の生PCMを Realtime API が要求する24kHzへ変換する。

audioop は Python 3.13 で標準ライブラリから外れたため numpy で自前補間する。
チャンク境界でプツッと鳴らないよう、直前の最終サンプルを持ち越して補間する。
"""

from __future__ import annotations

import numpy as np

from config import SOURCE_RATE, TARGET_RATE

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
