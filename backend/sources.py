"""通話音声(MKVバイト列)の供給元。KVSからのライブ受信と、録音ファイルのリプレイ。

リプレイは開発用の生命線。毎回国際電話を架けなくても、recordings/call.mkv を
実時間相当のペースで流せば画面まで通しで試せる。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import boto3

from config import (
    AWS_REGION,
    KVS_STREAM_PREFIX,
    REPLAY_BYTES_PER_SEC,
    REPLAY_CHUNK_BYTES as _CHUNK,
)

log = logging.getLogger(__name__)


async def replay_file(path: Path, speed: float = 1.0) -> AsyncIterator[bytes]:
    """録音済みMKVを実時間相当のペースで流す。"""
    data = path.read_bytes()
    interval = _CHUNK / (REPLAY_BYTES_PER_SEC * speed)
    log.info("replay start: %s (%d bytes, %.1fx)", path.name, len(data), speed)
    for i in range(0, len(data), _CHUNK):
        yield data[i:i + _CHUNK]
        await asyncio.sleep(interval)
    log.info("replay done: %s", path.name)


def _kvs_client():
    return boto3.client("kinesisvideo", region_name=AWS_REGION)


def list_call_streams() -> list[dict]:
    """Connectが通話ごとに作るKVSストリームを新しい順に返す。"""
    resp = _kvs_client().list_streams(
        StreamNameCondition={
            "ComparisonOperator": "BEGINS_WITH",
            "ComparisonValue": KVS_STREAM_PREFIX,
        }
    )
    streams = [s for s in resp.get("StreamInfoList", []) if s.get("Status") == "ACTIVE"]
    streams.sort(key=lambda s: s["CreationTime"], reverse=True)
    return streams


async def stream_from_kvs(
    stream_arn: str, start_fragment: str | None = None
) -> AsyncIterator[bytes]:
    """GetMediaで通話音声をライブ受信する。boto3は同期なのでスレッドで読む。

    start_fragment(Connectがシグナリングで渡してくる通話先頭のフラグメント番号)が
    あればそこから読む。NOWで繋ぐと接続が済むまでの音声を取り逃す。
    """
    kvs = _kvs_client()
    endpoint = kvs.get_data_endpoint(StreamARN=stream_arn, APIName="GET_MEDIA")["DataEndpoint"]
    media = boto3.client("kinesis-video-media", endpoint_url=endpoint, region_name=AWS_REGION)
    selector: dict[str, str] = (
        {"StartSelectorType": "FRAGMENT_NUMBER", "AfterFragmentNumber": start_fragment}
        if start_fragment
        else {"StartSelectorType": "NOW"}
    )
    resp = media.get_media(StreamARN=stream_arn, StartSelector=selector)
    body = resp["Payload"]
    log.info("GetMedia connected: %s", stream_arn.rsplit("/", 2)[-2])
    try:
        while True:
            chunk = await asyncio.to_thread(body.read, _CHUNK)
            if not chunk:
                break
            yield chunk
    finally:
        await asyncio.to_thread(body.close)
        log.info("GetMedia closed")
