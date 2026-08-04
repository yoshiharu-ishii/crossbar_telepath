"""テストの前提を固める。

方針: **外部に一切出ない。** OpenAI・AWS・PostgreSQL・MinIOのどれにも触れず、
純粋なロジック(パース・変換・状態機械)だけを検証する。外部を含む検証は
合成通話のリプレイ(tools/make_test_call.py → /api/replay)が担っており、
ここと役割を分ける。

環境変数は config が import される**前**に固定する必要がある(config.py は
import時に .env を読むが、load_dotenv は既存の環境変数を上書きしないため、
ここで設定した値が勝つ)。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# .env の値(実DB・実MinIO)がテストに漏れないよう、config import前に固定する
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("S3_ENDPOINT_URL", "")
os.environ.setdefault("S3_BUCKET", "")
os.environ.setdefault("WATCH_CALLS", "0")
os.environ["DATABASE_URL"] = ""
os.environ["S3_ENDPOINT_URL"] = ""
os.environ["S3_BUCKET"] = ""
os.environ["WATCH_CALLS"] = "0"
# 開発者の.env(AUTH_ENABLED=1等)がテスト結果を変えないよう固定する。
# CIとローカルで同じ前提にしないと「ローカルでは通るのにCIで落ちる」が起きる
# (2026-08-04にDEV_TOOLSの既定値で実際に発生)
os.environ["AUTH_ENABLED"] = "0"
os.environ.pop("DEV_TOOLS", None)

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(REPO / "tools"))  # make_test_call のMKVビルダを実物ごとテストする
