"""台本から「通話の録音」を合成する。架電せずに判定を検証するための道具。

怒りの検証には怒った通話が要るが、一人で本気の怒りは作れないし、実架電は
国際通話料がかかる。TTSで音声を作り、KVSがよこすのと同じ形式のMKVに詰めれば、
リプレイ経路に流すだけで実架電と同じパイプラインを通せる。

音声はKVSと同じ条件(8kHz / 16bit / mono / 生L16、話者別2トラック)に揃える。
TTSの24kHzをそのまま使うと電話より綺麗すぎて検証にならないため、帯域も落とす。

使い方(backend/ から):
    OPENAI_API_KEY=... uv run --with httpx --with numpy \
        python ../tools/make_test_call.py --out ../recordings/angry_call.mkv
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

import httpx
import numpy as np

RATE = 8000  # KVS(Amazon Connect)と同じ
TTS_RATE = 24000
TTS_URL = "https://api.openai.com/v1/audio/speech"

# 台本。怒りが立ち上がっていく流れにする(判定はウィンドウで見るため)
SCRIPT: list[tuple[str, str, str]] = [
    # (話者, 台詞, TTSへの口調指示)
    ("agent", "解析を開始しました。ご用件をお話しください。", "落ち着いた案内の口調で"),
    ("customer", "もしもし、先週から言ってる件、どうなってますか。", "普通の問い合わせの口調で"),
    ("agent", "確認いたしますので少々お待ちください。", "丁寧な事務的口調で"),
    ("customer", "確認って、さっきもそう言いましたよね。いつまで待たせるんですか。",
     "少し苛立った、語気の強まった口調で"),
    ("agent", "申し訳ございません。", "恐縮した口調で"),
    ("customer", "謝れば済むと思ってんのか。あんたじゃ話にならん、責任者を出せよ今すぐ!",
     "強い怒りをぶつける、大きな声で"),
]


# 声のトーン判定を検証するための対照実験。**台詞は一字一句同じで口調だけ違う**。
# テキスト判定は同じスコアを出すはずなので、差が付けばそれは声からしか取れない情報。
_SAME_WORDS = [
    ("agent", "解析を開始しました。ご用件をお話しください。", "落ち着いた案内の口調で"),
    ("customer", "先日お願いした件、その後いかがでしょうか。", "{tone}"),
    ("agent", "確認いたしますので少々お待ちください。", "丁寧な事務的口調で"),
    ("customer", "もう三回目なんですけど。いつまで待てばいいですか。", "{tone}"),
    ("agent", "申し訳ございません。", "恐縮した口調で"),
    ("customer", "そうですか。では、いつ頃になるか教えてください。", "{tone}"),
]


def _same_words(tone: str) -> list[tuple[str, str, str]]:
    return [(sp, tx, tn.format(tone=tone)) for sp, tx, tn in _SAME_WORDS]


SCRIPTS: dict[str, list[tuple[str, str, str]]] = {
    "angry": SCRIPT,
    # 丁寧な言葉づかいを、穏やかに言う場合と、静かに怒って言う場合
    "calm": _same_words("落ち着いた、穏やかで感じの良い口調で"),
    "cold": _same_words(
        "言葉は丁寧だが、静かに強い怒りを抑えている口調で。"
        "声を低く硬くし、語尾を鋭く切り、抑揚を平坦にする"
    ),
    # cold は失敗した(音響的に calm と差が出なかった。2026-08-03実測で
    # 有声率24%・RMS差1dB・F0レンジもほぼ重なる)。TTSは「大声で怒鳴る」は
    # 演じられるが「静かに抑えた怒り」は描き分けられない。
    # そこでTTSが確実に描ける対比に変えたのが loud。**台詞は calm と同一**
    "loud": _same_words(
        "激昂して怒鳴りつける口調で。大きな声で、語気を荒げ、語一語を強く叩きつける"
    ),
}


# ---- TTS -----------------------------------------------------------------


def synth(text: str, instructions: str, voice: str, key: str) -> np.ndarray:
    """OpenAI TTSで24kHzのPCMを得る。"""
    r = httpx.post(
        TTS_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "gpt-4o-mini-tts",
            "voice": voice,
            "input": text,
            "instructions": instructions,
            "response_format": "pcm",  # 24kHz / 16bit / mono
        },
        timeout=120,
    )
    r.raise_for_status()
    return np.frombuffer(r.content, dtype="<i2")


def to_telephone_band(x: np.ndarray) -> np.ndarray:
    """24kHz → 8kHz。折り返しを防ぐため先に低域だけ残す。

    電話帯域に落とすこと自体が検証の一部。TTSの綺麗な音のままでは、
    実際の通話で起きる聞き取り困難を再現できない。
    """
    taps = np.hamming(61) * np.sinc(np.arange(-30, 31) * 2 * 3400 / TTS_RATE)
    taps /= taps.sum()
    filtered = np.convolve(x.astype(np.float64), taps, mode="same")
    return np.rint(filtered[::3]).clip(-32768, 32767).astype("<i2")


# ---- MKV(KVSが出すのと同じ形) -------------------------------------------


def _vint(value: int, length: int) -> bytes:
    """EBMLの可変長整数(サイズ用。先頭にマーカービットを立てる)。"""
    return (value | (1 << (7 * length))).to_bytes(length, "big")


def _elem(elem_id: bytes, payload: bytes) -> bytes:
    return elem_id + _vint(len(payload), 8) + payload


def _track_entry(number: int, name: str) -> bytes:
    return _elem(
        b"\xae",
        _elem(b"\xd7", bytes([number]))                    # TrackNumber
        + _elem(b"\x53\x6e", name.encode())                # Name
        # CodecIDは実機と同じく "A_AAC" を名乗らせる(中身は生L16のまま)。
        # 詐称ごと再現しておかないと、実データで起きる問題が試験で出ない
        + _elem(b"\x86", b"A_AAC"),
    )


def _simple_block(track: int, pcm: bytes) -> bytes:
    body = bytes([0x80 | track]) + struct.pack(">h", 0) + b"\x80" + pcm
    return _elem(b"\xa3", body)


def build_mkv(customer: np.ndarray, agent: np.ndarray) -> bytes:
    """話者別PCMを、KVSが出すのと同じ構造のMKVに詰める。"""
    n = max(customer.size, agent.size)
    cust = np.pad(customer, (0, n - customer.size))
    agnt = np.pad(agent, (0, n - agent.size))

    tracks = _elem(
        b"\x16\x54\xae\x6b",
        _track_entry(1, "AUDIO_TO_CUSTOMER") + _track_entry(2, "AUDIO_FROM_CUSTOMER"),
    )

    step = RATE * 20 // 1000  # 20msずつ交互に積む(実機と同じ粒度)
    blocks = []
    for i in range(0, n, step):
        blocks.append(_simple_block(1, agnt[i:i + step].tobytes()))
        blocks.append(_simple_block(2, cust[i:i + step].tobytes()))
    cluster = _elem(b"\x1f\x43\xb6\x75", _elem(b"\xe7", b"\x00") + b"".join(blocks))

    # EBMLヘッダは中身を見ていないので最小限。Segmentの下にTracksとClusterを置く
    header = _elem(b"\x1a\x45\xdf\xa3", _elem(b"\x42\x82", b"matroska"))
    return header + _elem(b"\x18\x53\x80\x67", tracks + cluster)


# ---- 組み立て -------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="出力先のMKV")
    ap.add_argument("--gap", type=float, default=1.5, help="発話の間隔(秒)")
    ap.add_argument("--script", default="angry", choices=list(SCRIPTS),
                    help="台本。calm/cold は同一台詞で口調だけ変えた対照実験用")
    ap.add_argument("--customer-voice", default="ash")
    ap.add_argument("--agent-voice", default="alloy")
    args = ap.parse_args()

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY が未設定")

    tracks = {"customer": [], "agent": []}
    cursor = 0  # 現在位置(サンプル数)。話者をまたいで時間軸を共有する
    gap = int(RATE * args.gap)

    for speaker, text, tone in SCRIPTS[args.script]:
        voice = args.customer_voice if speaker == "customer" else args.agent_voice
        pcm = to_telephone_band(synth(text, tone, voice, key))
        other = "agent" if speaker == "customer" else "customer"
        # 喋る側にはこの位置から音を置き、相手側には同じ長さの無音を置く
        tracks[speaker].append((cursor, pcm))
        tracks[other].append((cursor, np.zeros(pcm.size, dtype="<i2")))
        print(f"  {speaker:8s} {pcm.size/RATE:4.1f}秒 | {text[:28]}")
        cursor += pcm.size + gap

    def assemble(parts: list[tuple[int, np.ndarray]]) -> np.ndarray:
        buf = np.zeros(cursor, dtype="<i2")
        for at, pcm in parts:
            buf[at:at + pcm.size] = pcm
        return buf

    mkv = build_mkv(assemble(tracks["customer"]), assemble(tracks["agent"]))
    with open(args.out, "wb") as f:
        f.write(mkv)
    print(f"\n書き出し: {args.out} ({len(mkv):,} bytes / {cursor/RATE:.1f}秒)")


if __name__ == "__main__":
    main()
