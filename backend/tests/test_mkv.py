"""MKVパーサの検証。

素材は tools/make_test_call.py の**実物のビルダ**で作る。テスト用に別実装を
持つと、ビルダとパーサが同じ誤解をしていても通ってしまうため……ではなく逆で、
KVS実機との一致は過去に実録音とのバイト一致で検証済み(PR #1)。以降はこの
ビルダを「KVS形式の定義」として使ってよい、という整理。
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from make_test_call import build_mkv
from mkv import MkvStreamParser


def _tone(freq: float, sec: float, rate: int = 8000) -> np.ndarray:
    t = np.arange(int(rate * sec)) / rate
    return (np.sin(2 * np.pi * freq * t) * 8000).astype("<i2")


@pytest.fixture()
def mkv_bytes() -> bytes:
    # 話者ごとに違う周波数を入れて、取り違えを検出できるようにする
    return build_mkv(customer=_tone(440, 1.0), agent=_tone(880, 1.0))


def _parse_all(data: bytes, chunks: list[bytes]) -> tuple[dict, dict]:
    p = MkvStreamParser()
    pcm: dict[int, bytearray] = {}
    for c in chunks:
        for b in p.feed(c):
            pcm.setdefault(b.track, bytearray()).extend(b.pcm)
    return pcm, p.track_names


def test_track_names_and_speaker_mapping(mkv_bytes):
    _, names = _parse_all(mkv_bytes, [mkv_bytes])
    assert names == {1: "AUDIO_TO_CUSTOMER", 2: "AUDIO_FROM_CUSTOMER"}


def test_codec_id_deception_is_reproduced(mkv_bytes):
    # 実機の詐称を再現していること自体を固定する。ここが A_PCM に「直って」
    # しまうと、実データで起きる問題が試験で出なくなる
    assert b"A_AAC" in mkv_bytes


def test_chunked_parse_equals_whole_parse(mkv_bytes):
    """どんな刻み方で食わせてもバイト一致で同じPCMが出ること。

    KVSのGetMediaは任意の位置でチャンクが切れるため、ここが最重要の性質。
    """
    whole, _ = _parse_all(mkv_bytes, [mkv_bytes])
    rng = random.Random(20260803)
    for _ in range(5):
        chunks, i = [], 0
        while i < len(mkv_bytes):
            n = rng.randint(1, 4097)
            chunks.append(mkv_bytes[i : i + n])
            i += n
        chunked, _ = _parse_all(mkv_bytes, chunks)
        assert chunked.keys() == whole.keys()
        for track in whole:
            assert bytes(chunked[track]) == bytes(whole[track]), f"track {track} mismatch"


def test_tracks_are_not_swapped(mkv_bytes):
    """customer(440Hz)とagent(880Hz)が入れ替わっていないこと。"""
    pcm, names = _parse_all(mkv_bytes, [mkv_bytes])
    by_name = {names[t]: np.frombuffer(bytes(p), dtype="<i2") for t, p in pcm.items()}

    def peak_freq(x: np.ndarray) -> float:
        spec = np.abs(np.fft.rfft(x.astype(np.float64)))
        return float(np.fft.rfftfreq(x.size, d=1 / 8000)[int(spec.argmax())])

    assert abs(peak_freq(by_name["AUDIO_FROM_CUSTOMER"]) - 440) < 5
    assert abs(peak_freq(by_name["AUDIO_TO_CUSTOMER"]) - 880) < 5
