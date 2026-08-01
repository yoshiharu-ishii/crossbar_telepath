"""相手が怒っているかを判定する。

**判定単位は発話1個ではなく直近数発話のウィンドウ。** 「もしもし」単体に感情は
乗らないし、怒りは流れの中で立ち上がるため。スコアは最新の発話に結び付けて表示するが、
意味は「その発話の時点での会話の状態」であって、その一言の性質ではない。

出力にはスコアだけでなく**状況の読み**(何に怒っていて何を求めているか)を添える。
オペレータに渡すのはセリフのカンペではなく状況情報にする、という設計方針
(相手から見て「AIにいなされている」と感じさせないため)。

コスト設計: ここはテキスト判定なので極めて安い(1通話1円未満)。通話時間ぶん課金される
音声判定は既定で止めてあり、テキストが閾値を超えたときだけ起動する想定(PH3後半)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from config import (
    ANGER_MIN_INTERVAL_SEC,
    ANGER_MODEL,
    ANGER_THRESHOLD,
    ANGER_WINDOW,
    CHAT_COMPLETIONS_URL,
    get_api_key,
)

log = logging.getLogger(__name__)

SPEAKER_LABEL = {"customer": "相手", "agent": "オペレータ"}

_SYSTEM = """あなたはコールセンターの通話を監視し、相手(顧客)の怒りの度合いを判定する。

直近のやりとりを読み、**相手の**怒りを0-100で評価する。オペレータ側の発話は文脈として
読むだけで、評価対象にしない。

判定の目安:
- 0-30 平静。通常の問い合わせや雑談
- 31-69 苛立ちの兆候。語気の強まり、同じ要求の繰り返し、皮肉、話を遮る
- 70-100 明確な怒り。罵倒、脅し、人格否定、対応そのものの全否定

reason は「何に対して怒っているか」「相手が本当に求めているもの」を一行で書く。
オペレータが読む状況説明であり、話すべきセリフではない。平静なら状況を短く書く。

会話が短く判断材料が乏しいときは、無理に高い値を付けず0-30に寄せること。"""

_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "anger_judgment",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "anger": {"type": "integer", "description": "0-100の怒り度"},
                "reason": {"type": "string", "description": "状況の読み(一行)"},
            },
            "required": ["anger", "reason"],
            "additionalProperties": False,
        },
    },
}


def build_window(messages: list[dict], size: int = ANGER_WINDOW) -> list[dict]:
    """判定に使う直近の発話。話者ラベル付きで返す。"""
    return [m for m in messages if m.get("final") and m.get("text")][-size:]


def render_window(window: list[dict]) -> str:
    return "\n".join(
        f"{SPEAKER_LABEL.get(m.get('speaker'), m.get('speaker'))}: {m.get('text')}"
        for m in window
    )


async def judge(window: list[dict]) -> dict | None:
    """ウィンドウを判定する。失敗したらNone(通話の処理は止めない)。"""
    if not window:
        return None
    key = get_api_key()
    if not key:
        log.warning("APIキーが無いため怒り判定をしない")
        return None

    payload = {
        "model": ANGER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": render_window(window)},
        ],
        "response_format": _SCHEMA,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                CHAT_COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
    except Exception:
        log.exception("怒り判定に失敗")
        return None

    score = max(0, min(100, int(result.get("anger", 0))))
    return {
        "score": score,
        "reason": (result.get("reason") or "").strip(),
        "window": len(window),
        "alert": score >= ANGER_THRESHOLD,
    }


class AngerWatcher:
    """1つの呼に張り付いて、相手の発話が確定するたびに判定する。

    デバウンスを入れて、連続発話でAPIを叩きすぎないようにする。
    """

    def __init__(self, contact_id: str, emit: Callable[[dict], Awaitable[None]]) -> None:
        self.contact_id = contact_id
        self._emit = emit
        self._last_at = 0.0
        self._busy = False
        # 判定中・間隔内に来た発話は捨てずに「最新の1件」として予約する
        self._pending: tuple[list[dict], dict] | None = None
        self.max_score = 0

    def should_judge(self, msg: dict) -> bool:
        """相手の確定発話だけを対象にする。間隔の制御は run() が持つ。"""
        return bool(
            msg.get("speaker") == "customer" and msg.get("final") and msg.get("text")
        )

    async def run(self, messages: list[dict], target: dict) -> None:
        """判定して、対象の発話に結果を書き込みブラウザへ流す。

        間隔を空けるが**発話は捨てない**。判定中に来たものは最新の1件に畳み込み、
        直前の判定が終わり次第それを判定する。捨てる実装にすると、発話が立て込む
        場面——つまり怒りが高まっている場面——ほど判定が抜ける。
        """
        self._pending = (messages, target)
        if self._busy:
            return  # 走っているループが拾う
        self._busy = True
        try:
            while self._pending is not None:
                wait = ANGER_MIN_INTERVAL_SEC - (time.monotonic() - self._last_at)
                if wait > 0:
                    await asyncio.sleep(wait)
                msgs, tgt = self._pending
                self._pending = None
                self._last_at = time.monotonic()

                result = await judge(build_window(msgs))
                if result is None:
                    continue

                # 発話そのものにスコアを載せる(記録にもそのまま残る)
                tgt["anger_score"] = result["score"]
                tgt["anger_reason"] = result["reason"]
                self.max_score = max(self.max_score, result["score"])

                await self._emit({
                    "type": "emotion",
                    "speaker": "customer",
                    "item_id": tgt.get("item_id"),
                    **result,
                })
        finally:
            self._busy = False
