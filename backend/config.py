"""環境変数と定数。他のモジュールはここから設定を読む。"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent  # backend/
FRONTEND_DIR = BASE_DIR.parent / "frontend"
RECORDINGS_DIR = Path(os.getenv("RECORDINGS_DIR", BASE_DIR.parent / "recordings"))
# 呼ごとの録音(MKV)と履歴(JSON)の置き場。通話録音なのでgit管理外
CALLS_DIR = RECORDINGS_DIR / "calls"

load_dotenv(BASE_DIR / ".env")

AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")

# Connectが通話ごとに作るKVSストリーム名の頭。infra/の var.project と揃える
KVS_STREAM_PREFIX = os.getenv("KVS_STREAM_PREFIX", "crossbar-telepath")

# 呼の設定が届くシグナリング用キュー(infra/signaling.tf が作る)
CALL_EVENTS_QUEUE = os.getenv("CALL_EVENTS_QUEUE", f"{KVS_STREAM_PREFIX}-call-events")
SQS_WAIT_SECONDS = int(os.getenv("SQS_WAIT_SECONDS", "20"))

# Connectのメディアストリーミングは 8kHz / 16bit / mono の生PCM
SOURCE_RATE = 8000
# Realtime APIに渡すサンプリングレート
TARGET_RATE = 24000
SAMPLE_WIDTH = 2

REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-transcribe")
TRANSCRIBE_LANGUAGE = os.getenv("TRANSCRIBE_LANGUAGE", "ja")
# 無音がこの長さ続いたら一区切りとみなす(server VAD)
VAD_SILENCE_MS = int(os.getenv("VAD_SILENCE_MS", "500"))

# MKVのトラック名 → 画面上の話者ラベル
SPEAKER_BY_TRACK_NAME = {
    "AUDIO_FROM_CUSTOMER": "customer",  # 相手の声
    "AUDIO_TO_CUSTOMER": "agent",  # こちら側(Connectが流す音)
}


def get_openai_api_key() -> str:
    """接続ごとに .env を読み直す(キー追記後の再起動を不要にする)。"""
    load_dotenv(BASE_DIR / ".env", override=True)
    return os.getenv("OPENAI_API_KEY", "")
