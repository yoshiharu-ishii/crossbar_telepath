"""通話録音の置き場。S3互換API(開発はMinIO、本番はS3)。

boto3の `endpoint_url` を差し替えるだけで MinIO ↔ S3 が切り替わるので、
開発と本番でコードパスが分岐しない。`S3_BUCKET` が未設定ならローカル
ファイルにフォールバックするため、コンテナを立てずに開発することもできる。

移行期の配慮として、読み出しはオブジェクトストレージ → ローカルの順に探す。
これで既存の recordings/calls/*.mkv が移行前でもそのまま見え続ける。
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from config import (
    AWS_REGION,
    CALLS_DIR,
    S3_ACCESS_KEY,
    S3_BUCKET,
    S3_ENDPOINT_URL,
    S3_SECRET_KEY,
)

log = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_PREFIX = "calls/"


def _check_id(contact_id: str) -> str:
    if not _SAFE_ID.fullmatch(contact_id):
        raise ValueError(f"不正なcontact_id: {contact_id!r}")
    return contact_id


def _key(contact_id: str) -> str:
    return f"{_PREFIX}{_check_id(contact_id)}.mkv"


def local_path(contact_id: str) -> Path:
    """ローカル保存時のパス(フォールバック先)。"""
    return CALLS_DIR / f"{_check_id(contact_id)}.mkv"


def enabled() -> bool:
    """オブジェクトストレージを使う設定になっているか。"""
    return bool(S3_BUCKET)


@lru_cache(maxsize=1)
def _client():
    """S3互換クライアント。

    MinIOの資格情報は**このクライアントにだけ**渡す。環境変数の
    AWS_ACCESS_KEY_ID等に置くと、SQSやKVSまで同じ鍵で認証しようとして壊れる。
    endpoint_url が空なら本物のS3を見る(認証はIAMロール)。
    """
    creds = {}
    if S3_ACCESS_KEY and S3_SECRET_KEY:
        creds = {"aws_access_key_id": S3_ACCESS_KEY, "aws_secret_access_key": S3_SECRET_KEY}
    return boto3.client(
        "s3", region_name=AWS_REGION, endpoint_url=S3_ENDPOINT_URL or None, **creds
    )


def put_recording(contact_id: str, data: bytes) -> None:
    """録音を保存する。通話終了時に一度だけ呼ぶ。"""
    if enabled():
        _client().put_object(Bucket=S3_BUCKET, Key=_key(contact_id), Body=data)
        log.info("recording uploaded: s3://%s/%s (%d bytes)", S3_BUCKET, _key(contact_id), len(data))
        return
    path = local_path(contact_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    log.info("recording saved: %s (%d bytes)", path.name, len(data))


def get_recording(contact_id: str) -> bytes | None:
    """録音を取り出す。無ければ None。"""
    if enabled():
        try:
            return _client().get_object(Bucket=S3_BUCKET, Key=_key(contact_id))["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("NoSuchKey", "404"):
                raise
    path = local_path(contact_id)
    return path.read_bytes() if path.exists() else None


def has_recording(contact_id: str) -> bool:
    try:
        if enabled():
            try:
                _client().head_object(Bucket=S3_BUCKET, Key=_key(contact_id))
                return True
            except ClientError:
                pass
            except Exception as e:
                # ストレージが落ちていても履歴一覧は出す(録音の有無だけ諦める)。
                # ここが例外を上げると /api/history 全体が500になり、
                # MinIO停止=画面全滅という壊れ方をする(2026-08-04に実際に発生)
                log.warning("録音ストレージに届かない(録音なし扱い): %s", e)
        return local_path(contact_id).exists()
    except ValueError:
        return False


def list_recorded_ids() -> set[str]:
    """録音のあるcontact_idの集合。一覧表示で1呼ずつ問い合わせないため。"""
    ids: set[str] = set()
    if enabled():
        paginator = _client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=_PREFIX):
            for obj in page.get("Contents", []):
                name = obj["Key"][len(_PREFIX):]
                if name.endswith(".mkv"):
                    ids.add(name[: -len(".mkv")])
    if CALLS_DIR.exists():
        ids |= {p.stem for p in CALLS_DIR.glob("*.mkv")}
    return ids
