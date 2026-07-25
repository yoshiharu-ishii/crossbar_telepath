"""KVS(Amazon Connect)のMKVバイトストリームを逐次パースする。

tools/extract_audio.py はファイル全体をebmliteに渡す方式だったが、こちらは
GetMediaのStreamingBodyから届いた分だけを食わせて、取り出せたSimpleBlockを
その場で吐き出す。リアルタイム分析のための書き換え。

KVSのMKVで踏んだ罠(2026-07-12の実測):
- CodecIDは "A_AAC" を名乗るが中身は生L16 PCM(8kHz/16bit/mono/リトルエンディアン)
- フラグメントごとにEBMLヘッダとSegmentが再出現する。Segmentは長さ未知(unknown-length)
- トラック番号と話者の対応は決め打ちせずTracks要素から読む
  (実測では 1=AUDIO_TO_CUSTOMER、2=AUDIO_FROM_CUSTOMER だが、これに依存しない)
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 中に降りていくマスター要素だけを列挙し、それ以外はサイズ分読み飛ばす
ID_SEGMENT = 0x18538067
ID_CLUSTER = 0x1F43B675
ID_TRACKS = 0x1654AE6B
ID_TRACK_ENTRY = 0xAE
DESCEND = {ID_SEGMENT, ID_CLUSTER, ID_TRACKS, ID_TRACK_ENTRY}

ID_SIMPLE_BLOCK = 0xA3
ID_TRACK_NUMBER = 0xD7
ID_TRACK_NAME = 0x536E


class _NeedMore(Exception):
    """バッファが足りない。次のfeedを待つ。"""


def _read_vint(buf: bytes, pos: int, *, keep_marker: bool) -> tuple[int, int, bool]:
    """EBMLの可変長整数を読む。(値, 消費バイト数, 長さ未知フラグ) を返す。

    要素IDはマーカービットを含んだ値を慣例として使い(keep_marker=True)、
    サイズはマーカービットを落とした値を使う。
    """
    if pos >= len(buf):
        raise _NeedMore
    first = buf[pos]
    if first == 0:
        # 8バイト超のvintは実質使われない。壊れたストリーム扱い
        raise ValueError("invalid vint: leading zero byte")
    mask = 0x80
    length = 1
    while not first & mask:
        mask >>= 1
        length += 1
    if pos + length > len(buf):
        raise _NeedMore

    value = first if keep_marker else first & (mask - 1)
    for i in range(1, length):
        value = (value << 8) | buf[pos + i]

    # データビットが全て1のサイズは「長さ未知」を意味する(KVSのSegmentがこれ)
    unknown = False
    if not keep_marker:
        all_ones = (1 << (7 * length)) - 1
        unknown = value == all_ones
    return value, length, unknown


@dataclass
class Block:
    """SimpleBlockから取り出した1フレーム分の音声。"""

    track: int
    pcm: bytes


@dataclass
class MkvStreamParser:
    """MKVのバイト列を少しずつ食べて、SimpleBlockを吐き出す。"""

    track_names: dict[int, str] = field(default_factory=dict)
    _buf: bytearray = field(default_factory=bytearray)
    _track_ctx: dict[str, int | str] = field(default_factory=dict)

    def feed(self, data: bytes) -> list[Block]:
        """受信バイトを追加し、取り出せたブロックを返す。"""
        self._buf.extend(data)
        blocks: list[Block] = []
        pos = 0
        while pos < len(self._buf):
            try:
                consumed = self._parse_element(pos, blocks)
            except _NeedMore:
                break
            pos += consumed
        # 消費済みを捨てる(長時間の通話でバッファが膨らまないように)
        if pos:
            del self._buf[:pos]
        return blocks

    def _parse_element(self, pos: int, blocks: list[Block]) -> int:
        buf = self._buf
        elem_id, id_len, _ = _read_vint(buf, pos, keep_marker=True)
        size, size_len, unknown = _read_vint(buf, pos + id_len, keep_marker=False)
        header = id_len + size_len

        # マスター要素は中身をそのまま次のループで解析させる=ヘッダだけ消費する
        if elem_id in DESCEND:
            if elem_id == ID_TRACK_ENTRY:
                self._track_ctx = {}
            return header

        if unknown:
            # 降りない要素で長さ未知は解釈不能。ここに来たらストリームが壊れている
            raise ValueError(f"unknown-length non-master element: {elem_id:#x}")

        end = pos + header + size
        if end > len(buf):
            raise _NeedMore
        payload = bytes(buf[pos + header:end])

        if elem_id == ID_SIMPLE_BLOCK:
            blocks.append(self._decode_simple_block(payload))
        elif elem_id == ID_TRACK_NUMBER:
            self._track_ctx["number"] = int.from_bytes(payload, "big")
            self._flush_track_ctx()
        elif elem_id == ID_TRACK_NAME:
            self._track_ctx["name"] = payload.decode("utf-8", "replace")
            self._flush_track_ctx()

        return header + size

    def _flush_track_ctx(self) -> None:
        num = self._track_ctx.get("number")
        name = self._track_ctx.get("name")
        if isinstance(num, int) and isinstance(name, str):
            self.track_names[num] = name

    @staticmethod
    def _decode_simple_block(payload: bytes) -> Block:
        """SimpleBlock = トラック番号(vint) + 相対タイムコード(int16) + フラグ(1) + 音声。"""
        track, track_len, _ = _read_vint(payload, 0, keep_marker=False)
        return Block(track=track, pcm=payload[track_len + 3:])
