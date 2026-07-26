"""呼の設定を受け取るシグナリング経路(SQS)。

通話路(KVS)とは別の線で「いま呼が張られた。ContactIdはこれ、音声はこのストリームの
このフラグメントから」という情報が届く。KVSのストリーム一覧から呼の存在を推測する
方式と違い、呼とストリームの対応がConnectから直接渡るので取り違えようがない。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import boto3

from config import AWS_REGION, CALL_EVENTS_QUEUE, SQS_WAIT_SECONDS

log = logging.getLogger(__name__)


class CallEvent(dict):
    """Lambdaが送ってくる呼の同定情報。"""

    @property
    def contact_id(self) -> str:
        return self.get("contact_id", "")

    @property
    def stream_arn(self) -> str | None:
        return self.get("stream_arn")

    @property
    def start_fragment(self) -> str | None:
        return self.get("start_fragment")

    @property
    def customer_number(self) -> str | None:
        return self.get("customer_number")


async def poll_call_events() -> AsyncIterator[CallEvent]:
    """SQSをロングポーリングし、届いた呼イベントを順に返す。"""
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    url = (await asyncio.to_thread(sqs.get_queue_url, QueueName=CALL_EVENTS_QUEUE))["QueueUrl"]
    log.info("signaling queue: %s", url)

    while True:
        try:
            resp = await asyncio.to_thread(
                sqs.receive_message,
                QueueUrl=url,
                WaitTimeSeconds=SQS_WAIT_SECONDS,
                MaxNumberOfMessages=10,
            )
        except Exception:
            log.exception("SQS receive failed")
            await asyncio.sleep(5)
            continue

        for m in resp.get("Messages", []):
            # 処理の成否によらず削除する。失敗した呼を再配信しても
            # 通話は既に進んでいて追いつけないため
            await asyncio.to_thread(
                sqs.delete_message, QueueUrl=url, ReceiptHandle=m["ReceiptHandle"]
            )
            try:
                yield CallEvent(json.loads(m["Body"]))
            except json.JSONDecodeError:
                log.warning("不正なメッセージを捨てた: %r", m["Body"][:200])
