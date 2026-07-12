"""KVS(Amazon Connect)のMKVから話者別の生PCMを剥がしてWAV化する。

使い方:
    # list-fragments → get-media-for-fragment-list でMKVを落とした後:
    uv run --with ebmlite python tools/extract_audio.py call.mkv

2026-07-12の実測(PH1検証通話)で確定した事実:
- トラック1 = AUDIO_TO_CUSTOMER(Connect→発信者)、トラック2 = AUDIO_FROM_CUSTOMER(発信者の声)
- 中身は L16(16bit signed LE)8kHz mono の生PCM
- ただし CodecID は "A_AAC" を名乗っている(罠)。ffmpegはAACとして
  デコードしようとして全フレーム失敗するため、EBMLを自前で歩く必要がある
- SimpleBlockの先頭4バイト(トラック番号vint 1B + 相対タイムコード2B + フラグ1B)を
  剥がした残りがPCMペイロード
"""
import sys
import wave
from ebmlite import loadSchema

SAMPLE_RATE = 8000

def walk(el, depth=0):
    if el.name in ("Segment", "Cluster"):
        for child in el:
            yield from walk(child, depth + 1)
    elif el.name == "SimpleBlock":
        yield el

def parse_simple_block(data: bytes):
    """SimpleBlockのペイロードから (track_number, pcm_bytes) を返す"""
    first = data[0]
    # トラック番号はEBML vint。トラック数が少ないので1バイト(0x80|n)前提
    if not (first & 0x80):
        raise ValueError("multi-byte track number not supported")
    track = first & 0x7F
    # 続く2バイト=相対タイムコード、1バイト=フラグ、以降がフレームデータ
    return track, data[4:]

def main(path: str):
    schema = loadSchema("matroska.xml")
    doc = schema.load(path)
    tracks: dict[int, bytearray] = {}
    for block in (b for el in doc for b in walk(el)):
        track, pcm = parse_simple_block(block.value)
        tracks.setdefault(track, bytearray()).extend(pcm)

    # Tracks要素の実測: TrackNumber 1 = AUDIO_TO_CUSTOMER, 2 = AUDIO_FROM_CUSTOMER
    # (CodecIDは"A_AAC"を名乗るが中身は生L16 PCM。ffmpegはこれで誤認する)
    names = {1: "to_customer", 2: "from_customer"}
    for track, pcm in sorted(tracks.items()):
        name = names.get(track, f"track{track}")
        out = f"{name}.wav"
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(bytes(pcm))
        dur = len(pcm) / 2 / SAMPLE_RATE
        print(f"track {track} -> {out}: {len(pcm):,} bytes, {dur:.1f}s")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "call.mkv")
