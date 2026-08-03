"""声のトーンから怒りを判定する。

テキスト判定(emotion.py)は「何を言ったか」しか見ない。だが電話帯域では4kHz超が
物理的に落ちており、子音の識別に効く高域が失われている(実測で3-4kHz成分は2.3%)。
罵倒語の聞き取りに依存する設計は、そもそも脆い。

**トーン(韻律・音量・ピッチ)は帯域制限に強く残る。** 言葉は丁寧なのに声が怒っている
場面——「そうですか。」を凍った声で言われる——はテキストでは原理的に取れない。
そこを埋めるのがこの判定であって、あれば良い機能ではなく核心機能である。

コスト設計: 音声入力は通話時間ぶん課金されるため常時は回さない。テキスト判定が
トリガ閾値(既定45)に届いたときだけ、直近数秒を切り出して1回投げる。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
import wave
from collections.abc import Awaitable, Callable

import httpx
import numpy as np

from config import (
    CHAT_COMPLETIONS_URL,
    SAMPLE_WIDTH,
    SOURCE_RATE,
    VOICE_JUDGE_INTERVAL_SEC,
    VOICE_JUDGE_MODE,
    VOICE_JUDGE_MODEL,
    VOICE_TRIGGER_SCORE,
    get_api_key,
)

# 実測で決めた定数(2026-08-03)。設定にしない——「変えられるが変える理由が無い」
# 項目を.envに並べても選択肢が増えるだけで、値の根拠はここに書いておく方が役に立つ
VOICE_WINDOW_SEC = 12.0        # 判定に使う直近の秒数。長いと課金増、短いとトーンが読めない
VOICE_MIN_SEC = 5.0            # これ未満はモデルが「音声が聞こえない」と返すだけで課金される
VOICE_MIN_VOICED_SEC = 2.0     # 窓は時間で切るので、中身(有声秒数)でも足切りする

log = logging.getLogger(__name__)

_SYSTEM = """あなたはコールセンターの通話音声を聴いて、話者(顧客)の**声の調子**から
怒りの度合いを判定する。

**判断材料は声だけにすること。** 語句の意味や丁寧さではなく、声量・話速・語気の鋭さ・
声の震え・抑揚の平坦さ・語尾の強さといった音の性質から判断する。丁寧な言葉づかいでも
声が刺々しければ高く、乱暴な言葉でも笑い混じりで穏やかなら低く付ける。

判定の目安:
- 0-30 平静。普通の話し声
- 31-69 苛立ちの兆候。語気が強まる、話速が上がる、抑揚が硬い
- 70-100 明確な怒り。怒鳴る、声を荒げる、詰めるような低く鋭い声

tone は声の様子そのものを一行で書く(何を言ったかではなく、どう聞こえるか)。
音声が短い・無音・聞き取れない場合は無理に高い値を付けず0-30に寄せること。

出力は次の形のJSONだけを返すこと。前後に説明を付けない。
{"anger": 0から100の整数, "tone": "声の様子を一行で"}"""

# gpt-audio 系は response_format を一切受け付けない(json_schema も json_object も400)。
# スキーマはシステムプロンプトで指示し、崩れた応答は _parse が拾う


def _parse(content: str) -> dict | None:
    """JSONだけが返る想定だが、前後に文が付いても拾えるようにする。"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    i, j = content.find("{"), content.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(content[i : j + 1])
        except json.JSONDecodeError:
            pass
    log.warning("音声判定の応答がJSONでない: %s", content[:120])
    return None


def to_wav(pcm: np.ndarray) -> bytes:
    """8kHz/16bit/monoの生PCMをWAVに包む(APIがコンテナを要求するため)。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SOURCE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class VoiceBuffer:
    """相手の音声を直近数秒だけ保持する輪。

    通話全体を持つと長時間の呼でメモリを食うし、判定に要るのは直近だけ。
    """

    def __init__(self, seconds: float = VOICE_WINDOW_SEC) -> None:
        self._max = int(SOURCE_RATE * seconds)
        self._buf = np.zeros(0, dtype="<i2")

    def add(self, pcm: bytes) -> None:
        if not pcm:
            return
        self._buf = np.concatenate([self._buf, np.frombuffer(pcm, dtype="<i2")])
        if self._buf.size > self._max:
            self._buf = self._buf[-self._max :]

    def take(self) -> np.ndarray:
        return self._buf.copy()

    def voiced_seconds(self) -> float:
        """窓のうち、実際に声が入っている秒数。

        窓は時間で切るので、相手が黙っている間(こちらが喋っている間)は無音で埋まる。
        12秒の窓に声が0.3秒しか無い状態で投げると、モデルは「音声が聞こえない」と
        返すだけで課金される。**窓の長さではなく中身で足切りする必要がある。**
        """
        if self._buf.size == 0:
            return 0.0
        frame = SOURCE_RATE * 20 // 1000  # 20msごとに見る
        n = self._buf.size // frame
        if n == 0:
            return 0.0
        f = self._buf[: n * frame].astype(np.float64).reshape(n, frame)
        rms = np.sqrt((f**2).mean(axis=1)) / 32768
        with np.errstate(divide="ignore"):
            db = 20 * np.log10(np.maximum(rms, 1e-9))
        return float((db > -50).sum()) * frame / SOURCE_RATE


async def judge_voice(pcm: np.ndarray) -> dict | None:
    """音声を聴かせてトーンから判定する。失敗したらNone(通話の処理は止めない)。

    短すぎる音声はモデルが「音声が聞こえない」と返すだけなので、実測に基づいて
    下限を設けている(4秒未満は安定して拒否された)。
    """
    if pcm.size < SOURCE_RATE * VOICE_MIN_SEC:
        return None
    key = get_api_key()
    if not key:
        log.warning("APIキーが無いため音声判定をしない")
        return None

    payload = {
        "model": VOICE_JUDGE_MODEL,
        "modalities": ["text"],  # 音声で聴いてテキストで返す(トーンを失わない)
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                # **出力形式の指示をユーザーターンに書く。** systemに書くだけだと
                # モデルが「音声をお聞かせください」と、音声を添えているのに未受領扱いの
                # 応答を返す。2026-08-03に変数を分離して実測(gpt-audio、各5回):
                #   テキスト先・指示なし 0/5 / 音声先・指示なし 0/5
                #   テキスト先・指示あり 4/5 / 音声先・指示あり 5/5
                # **順序は効かない。効くのは形式指示の位置。** 音声先は誤差程度の上積み
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64.b64encode(to_wav(pcm)).decode(),
                            "format": "wav",
                        },
                    },
                    {
                        "type": "text",
                        "text": "上の音声の話者の怒りを判定し、JSONだけを返してください。"
                        '{"anger": 0から100の整数, "tone": "声の様子を一行で"}',
                    },
                ],
            },
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                CHAT_COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            if r.status_code >= 400:
                # 本文を出さないと400の原因が分からない(音声の長さや形式で弾かれる)
                log.error("音声判定 %s: %s", r.status_code, r.text[:300])
                return None
            content = r.json()["choices"][0]["message"]["content"]
        result = _parse(content)
        if result is None:
            return None
    except Exception:
        log.exception("音声判定に失敗")
        return None

    score = max(0, min(100, int(result.get("anger", 0))))
    return {
        "score": score,
        "tone": (result.get("tone") or "").strip(),
        "seconds": round(pcm.size / SOURCE_RATE, 1),
    }


class VoiceWatcher:
    """1つの呼に張り付き、テキスト判定が高いときだけ声を聴きに行く。

    常時聴取は無音も課金される側なので、安いテキスト判定で網を張り、
    高価な音声判定は必要な呼にだけ落とす(電話網の信号系と通話路の関係と同じ)。
    """

    def __init__(self, contact_id: str, emit: Callable[[dict], Awaitable[None]]) -> None:
        self.contact_id = contact_id
        self._emit = emit
        self.buffer = VoiceBuffer()
        self._last_at = 0.0
        self._busy = False
        self.max_score = 0

    @property
    def enabled(self) -> bool:
        return VOICE_JUDGE_MODE != "off"

    def should_judge(self, text_score: int) -> bool:
        """テキストがトリガ閾値に届き、かつ間隔が空いていること。

        always モードは検証用(全発話で聴く)。既定の auto はトリガ方式。
        """
        if not self.enabled or self._busy:
            return False
        if VOICE_JUDGE_MODE != "always" and text_score < VOICE_TRIGGER_SCORE:
            return False
        return (time.monotonic() - self._last_at) >= VOICE_JUDGE_INTERVAL_SEC

    async def run(self, target: dict) -> None:
        """判定して、対象の発話に結果を書き込みブラウザへ流す。"""
        self._busy = True
        self._last_at = time.monotonic()
        try:
            if self.buffer.voiced_seconds() < VOICE_MIN_VOICED_SEC:
                return  # 声がほとんど入っていない。投げても拒否されるうえ課金は乗る
            result = await judge_voice(self.buffer.take())
            if result is None:
                return

            target["voice_score"] = result["score"]
            target["voice_tone"] = result["tone"]
            self.max_score = max(self.max_score, result["score"])

            await self._emit({
                "type": "voice",
                "speaker": "customer",
                "item_id": target.get("item_id"),
                **result,
            })
        finally:
            self._busy = False
