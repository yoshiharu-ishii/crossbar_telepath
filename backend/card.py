"""通話カード。切断後に1回だけLLMを呼び、通話を構造化して残す。

**画面に出すだけでなくエクスポートできる形にするのが要点。** 通話中を見るのはこちら、
通話後を処理するのは別システム、という分担を想定しているため、受け渡し口になる
JSONのスキーマがそのまま連携の契約になる。

コスト設計: 呼あたり1回だけ。通話中に何度も回す種類の処理ではない。
"""

from __future__ import annotations

import json
import logging

import httpx

from config import CARD_MODEL, CHAT_COMPLETIONS_URL, get_api_key
from emotion import SPEAKER_LABEL

log = logging.getLogger(__name__)

_SYSTEM = """あなたはコールセンターの通話記録を読み、対応記録カードを作る。

**書き起こしは電話帯域(8kHz)の音声から起こしたもので、誤認識を含む。** 明らかな
聞き取り誤りは文脈から補って解釈してよいが、**推測で事実を足してはいけない**。
分からないことは分からないまま空欄にする。

各項目の書き方:
- summary: 何があった通話かを一行で。担当者以外が読んで分かる書き方にする
- topic: 相手の用件を短く(例「納期の遅延について」)
- next_action: こちらが次に取るべき行動。無ければ空文字
- callback_needed: 折り返しの約束や、回答を保留した事実があれば true
- callback_reason: true のときだけ、何を回答する約束かを書く
- unresolved: 通話中に解決しなかった点。無ければ空配列
- harassment: 暴言・脅迫・人格否定・過大要求など、カスタマーハラスメントに
  該当しうる言動があれば true。**声を荒げただけでは true にしない**
- harassment_quote: true のときだけ、根拠になる発言をそのまま引用する(記録として
  使うため要約しない)。無ければ空文字"""

_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "call_card",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "topic": {"type": "string"},
                "next_action": {"type": "string"},
                "callback_needed": {"type": "boolean"},
                "callback_reason": {"type": "string"},
                "unresolved": {"type": "array", "items": {"type": "string"}},
                "harassment": {"type": "boolean"},
                "harassment_quote": {"type": "string"},
            },
            "required": [
                "summary", "topic", "next_action", "callback_needed",
                "callback_reason", "unresolved", "harassment", "harassment_quote",
            ],
            "additionalProperties": False,
        },
    },
}


def render(messages: list[dict]) -> str:
    """判定に渡す本文。話者ラベル付きの素の書き起こし。"""
    return "\n".join(
        f"{SPEAKER_LABEL.get(m.get('speaker'), m.get('speaker'))}: {m.get('text')}"
        for m in messages
        if m.get("final") and m.get("text")
    )


async def make_card(messages: list[dict]) -> dict | None:
    """通話カードを作る。失敗したらNone(記録の保存自体は止めない)。"""
    body = render(messages)
    if not body.strip():
        return None
    key = get_api_key()
    if not key:
        log.warning("APIキーが無いため通話カードを作らない")
        return None

    payload = {
        "model": CARD_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": body},
        ],
        "response_format": _SCHEMA,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                CHAT_COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            if r.status_code >= 400:
                log.error("通話カード %s: %s", r.status_code, r.text[:300])
                return None
            content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        log.exception("通話カードの生成に失敗")
        return None
