"""怒り判定(テキスト)の状態機械。

一番大事なのは**デバウンスの畳み込み**の回帰テスト。かつて「判定中・間隔内の
発話を捨てる」実装で、発話が立て込む場面——怒りが高まる場面——ほど判定が
抜けるバグがあった(合成通話で発覚)。judge はモックし、外部には出ない。
"""

from __future__ import annotations

import asyncio

import pytest

import emotion
from emotion import AngerWatcher, build_window


def _msg(speaker="customer", text="こんにちは", final=True, item_id="i1"):
    return {"speaker": speaker, "text": text, "final": final, "item_id": item_id}


def test_build_window_takes_only_final_with_text():
    msgs = [
        _msg(text="a"),
        _msg(final=False, text="打鍵中"),
        _msg(text=""),
        _msg(speaker="agent", text="b"),
        _msg(text="c"),
    ]
    assert [m["text"] for m in build_window(msgs, size=10)] == ["a", "b", "c"]
    assert [m["text"] for m in build_window(msgs, size=2)] == ["b", "c"]


def test_should_judge_only_customer_final():
    w = AngerWatcher("c1", emit=None)
    assert w.should_judge(_msg())
    assert not w.should_judge(_msg(speaker="agent"))
    assert not w.should_judge(_msg(final=False))
    assert not w.should_judge(_msg(text=""))


@pytest.mark.asyncio
async def test_coalesce_never_drops_the_latest(monkeypatch):
    """立て込んだ発話でも**最新は必ず判定される**こと(デバウンスバグの回帰)。

    5発話を判定中に畳みかける。途中は間引かれてよいが、最後の1件が
    無判定のままなら、修正前のバグが再発している。
    """
    monkeypatch.setattr(emotion, "ANGER_MIN_INTERVAL_SEC", 0.0)
    judged: list[str] = []

    async def fake_judge(window):
        await asyncio.sleep(0.01)  # 判定中に次の発話が来る状況を作る
        judged.append(window[-1]["text"])
        return {"score": 50, "reason": "test", "window": len(window), "alert": False}

    monkeypatch.setattr(emotion, "judge", fake_judge)
    emitted = []

    async def emit(msg):
        emitted.append(msg)

    w = AngerWatcher("c1", emit=emit)
    messages = []
    tasks = []
    for i in range(5):
        m = _msg(text=f"発話{i}", item_id=f"i{i}")
        messages.append(m)
        tasks.append(asyncio.create_task(w.run(list(messages), m)))
        await asyncio.sleep(0.003)  # 判定(0.01s)より速く畳みかける
    await asyncio.gather(*tasks)

    assert judged, "1件も判定されていない"
    assert judged[-1] == "発話4", f"最新の発話が捨てられた: {judged}"
    assert messages[-1].get("anger_score") == 50, "最新の発話にスコアが載っていない"
    # 途中の間引きは正当(APIを叩きすぎない)。全件判定は要求しない
    assert len(judged) <= 5


@pytest.mark.asyncio
async def test_judge_failure_does_not_stall(monkeypatch):
    """judgeがNone(API失敗)でも次の判定に進めること。"""
    monkeypatch.setattr(emotion, "ANGER_MIN_INTERVAL_SEC", 0.0)
    calls = {"n": 0}

    async def flaky_judge(window):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return {"score": 30, "reason": "ok", "window": 1, "alert": False}

    monkeypatch.setattr(emotion, "judge", flaky_judge)

    async def emit(msg):
        pass

    w = AngerWatcher("c1", emit=emit)
    m1, m2 = _msg(item_id="a"), _msg(item_id="b")
    await w.run([m1], m1)
    await w.run([m1, m2], m2)
    assert "anger_score" not in m1  # 失敗した回はスコアが載らない
    assert m2["anger_score"] == 30  # 次の回は正常に動く
    assert w.max_score == 30
