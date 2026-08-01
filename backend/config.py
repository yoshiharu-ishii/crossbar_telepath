"""設定。変わりうる値は環境変数(.env)から読み、既定値だけをここに書く。

方針:
- **設定は .env に寄せる**。このファイルは「どんな設定があるか」の一覧であって、
  値そのものの置き場所ではない。項目を足したら `.env.example` にも必ず追記する
- **秘密**(APIキー・DB接続情報)も .env。本番では SSM SecureString 等から注入する
- **Amazon Connect の仕様で決まっている値だけ**を定数として末尾に残す。これらを
  設定にすると「変えられるが変えたら壊れる」項目が増えるだけなので、あえて出さない
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent  # backend/
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


# ---- パスと動作 -------------------------------------------------------
FRONTEND_DIR = BASE_DIR.parent / "frontend"
RECORDINGS_DIR = Path(os.getenv("RECORDINGS_DIR", BASE_DIR.parent / "recordings"))
CALLS_DIR = RECORDINGS_DIR / "calls"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# シグナリング(SQS)を監視して実通話を拾うか。偽ならリプレイ専用で動く
WATCH_CALLS = _bool("WATCH_CALLS", False)

# ---- AWS: 通話路とシグナリング ---------------------------------------
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
KVS_STREAM_PREFIX = os.getenv("KVS_STREAM_PREFIX", "crossbar-telepath")
CALL_EVENTS_QUEUE = os.getenv("CALL_EVENTS_QUEUE", f"{KVS_STREAM_PREFIX}-call-events")
SQS_WAIT_SECONDS = int(os.getenv("SQS_WAIT_SECONDS", "20"))
# 取り逃した呼を SearchContacts から復元するときだけ要る(通常運転では未使用)
CONNECT_INSTANCE_ID = os.getenv("CONNECT_INSTANCE_ID", "")

# ---- 推論エンドポイント -----------------------------------------------
# OpenAI互換のエンドポイントなら差し替えられる。ただしデータ主権が要件に
# なった場合の移行先は全AWS(Transcribe + Bedrock)を想定しており、そちらは
# URLの付け替えでは済まず Transcriber の実装ごと差し替えになる
REALTIME_URL = os.getenv(
    "REALTIME_URL", "wss://api.openai.com/v1/realtime?intent=transcription"
)

# ---- 文字起こし -------------------------------------------------------
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-transcribe")
TRANSCRIBE_LANGUAGE = os.getenv("TRANSCRIBE_LANGUAGE", "ja")
# 無音がこの長さ続いたら一区切りとみなす(server VAD)
VAD_SILENCE_MS = int(os.getenv("VAD_SILENCE_MS", "500"))
# 音声をこのミリ秒ぶん貯めてから送る(WSメッセージを細かく刻みすぎない)
AUDIO_FLUSH_MS = int(os.getenv("AUDIO_FLUSH_MS", "100"))

# ---- 感情判定(PH3) --------------------------------------------------
ANGER_MODEL = os.getenv("ANGER_MODEL", "gpt-4o-mini")
# 直近何発話をまとめて判定するか(発話1個には感情が乗らないため)
ANGER_WINDOW = int(os.getenv("ANGER_WINDOW", "5"))
# この怒り度を超えたらアラートを出す
ANGER_THRESHOLD = int(os.getenv("ANGER_THRESHOLD", "70"))
# 判定の最小間隔(秒)。連続発話でAPIを叩きすぎないためのデバウンス
ANGER_MIN_INTERVAL_SEC = float(os.getenv("ANGER_MIN_INTERVAL_SEC", "3"))
# 音声判定の起動方針: off | threshold(テキストが閾値超え時) | interval
# 音声入力は通話時間ぶん課金されるため、既定では止めておく
VOICE_JUDGE_MODE = os.getenv("VOICE_JUDGE_MODE", "off")
VOICE_JUDGE_INTERVAL_SEC = float(os.getenv("VOICE_JUDGE_INTERVAL_SEC", "30"))

# ---- 永続化(PH3) ----------------------------------------------------
# 空ならファイル(recordings/calls/*.json)にフォールバックする
DATABASE_URL = os.getenv("DATABASE_URL", "")
# MinIO利用時のみ設定。空なら本物のS3を見る(認証はIAMロール)
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
S3_BUCKET = os.getenv("S3_BUCKET", "")

# ---- 開発用 -----------------------------------------------------------
# リプレイの流速。実測(323KB / 9.7秒)に合わせた既定値
REPLAY_BYTES_PER_SEC = int(os.getenv("REPLAY_BYTES_PER_SEC", "33000"))
REPLAY_CHUNK_BYTES = int(os.getenv("REPLAY_CHUNK_BYTES", "4096"))
# 終了直後の呼をメモリに残す数(ディスクに書かないリプレイを選択可能にするため)
MAX_RECENT_CALLS = int(os.getenv("MAX_RECENT_CALLS", "10"))

# ---- プロトコル定数(Amazon Connectの仕様。設定にしない) -------------
# メディアストリーミングは 8kHz / 16bit / mono の生PCM(2026-07-12実測)
SOURCE_RATE = 8000
SAMPLE_WIDTH = 2
# Realtime APIが要求するレート
TARGET_RATE = 24000
# MKVのトラック名 → 画面上の話者ラベル(Tracks要素から読む値)
SPEAKER_BY_TRACK_NAME = {
    "AUDIO_FROM_CUSTOMER": "customer",  # 相手の声
    "AUDIO_TO_CUSTOMER": "agent",  # こちら側(Connectが流す音)
}


def get_api_key() -> str:
    """APIキー。接続ごとに .env を読み直す。

    キーを書き足した後にサーバーを再起動しなくて済むようにしている。
    """
    load_dotenv(BASE_DIR / ".env", override=True)
    return os.getenv("OPENAI_API_KEY", "")
