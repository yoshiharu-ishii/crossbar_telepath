"""コールフローから呼ばれ、呼の同定情報をSQSへ流すだけの関数。

通話路(KVS)とは別の経路で「いま呼が張られた」ことを伝えるシグナリング。
KVSのストリーム一覧をポーリングして呼の存在を推測する方式と違い、
ContactIdとStreamARNの対応がConnectから直接渡るので取り違えが起きない。

StartFragmentNumberが得られるのも重要で、これがあると通話の先頭から
受信できる(GetMediaのStartSelectorType=NOWだと接続までの音声を取り逃す)。
"""

import json
import os

import boto3

sqs = boto3.client("sqs")
QUEUE_URL = os.environ["QUEUE_URL"]


def handler(event, context):
    contact = event["Details"]["ContactData"]
    audio = (contact.get("MediaStreams") or {}).get("Customer", {}).get("Audio") or {}
    customer = contact.get("CustomerEndpoint") or {}

    message = {
        "contact_id": contact["ContactId"],
        "stream_arn": audio.get("StreamARN"),
        "start_fragment": audio.get("StartFragmentNumber"),
        "start_timestamp": audio.get("StartTimestamp"),
        "customer_number": customer.get("Address"),
        "instance_arn": contact.get("InstanceARN"),
    }
    print(f"call event: {json.dumps(message)}")

    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(message),
        # 同じ呼で複数回呼ばれても後段が気づけるようにしておく
        MessageAttributes={
            "contact_id": {"DataType": "String", "StringValue": contact["ContactId"]}
        },
    )
    # Connectへ返せるのは文字列の平坦なマップだけ
    return {"status": "ok", "contactId": contact["ContactId"]}
