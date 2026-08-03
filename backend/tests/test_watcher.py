"""シグナリング監視の自己修復(2026-08-03に入れた耐性の回帰テスト)。

監視が止まる=電話が鳴らなくなる、なので:
1. 呼イベント1件の異常でループが死なないこと
2. 監視タスク自体が死んだら起こし直すこと
"""

from __future__ import annotations

import asyncio

import pytest

import main
import signaling


@pytest.mark.asyncio
async def test_bad_events_do_not_kill_the_loop(monkeypatch):
    """壊れたARN・型違い・ARN欠落を食っても監視ループが完走すること。"""
    handled = []

    async def fake_events():
        for body in [
            {"contact_id": "bad1", "stream_arn": "garbage-no-slash"},  # rsplitで落ちる形
            {"contact_id": "bad2", "stream_arn": 12345},               # 型違い
            {"contact_id": "no-arn", "stream_arn": None},              # 警告経路
            {"contact_id": "ok", "stream_arn": "arn:aws:kvs/stream-name/123"},
        ]:
            yield signaling.CallEvent(body)

    def fake_start(session, source):
        handled.append(session.contact_id)

    monkeypatch.setattr(signaling, "poll_call_events", fake_events)
    monkeypatch.setattr(main, "_start_session", fake_start)
    monkeypatch.setattr(main.sources, "stream_from_kvs", lambda arn, frag: None)

    await main._watch_signaling()  # 例外がここへ漏れたら耐性が壊れている

    assert handled == ["ok"], "正常な呼だけが処理されるべき"


@pytest.mark.asyncio
async def test_watcher_restarts_after_crash(monkeypatch):
    """監視が落ちても _watch_forever が起こし直すこと。"""
    attempts = {"n": 0}

    async def dying():
        attempts["n"] += 1
        raise RuntimeError("simulated crash")

    real_sleep = asyncio.sleep

    async def no_wait(sec):
        await real_sleep(0)

    monkeypatch.setattr(main, "_watch_signaling", dying)
    monkeypatch.setattr(main.asyncio, "sleep", no_wait)

    task = asyncio.get_event_loop().create_task(main._watch_forever())
    await real_sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert attempts["n"] >= 2, f"再起動していない(試行{attempts['n']}回)"
