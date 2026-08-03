"""呼の記録(ファイルバックエンド)と通話カードの整形。"""

from __future__ import annotations

import pytest

import card
import history


# ---- history: ファイルバックエンドの往復 ----


@pytest.fixture()
def file_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "CALLS_DIR", tmp_path)
    # DATABASE_URL="" はconftestで固定済み(db.enabled()がFalse)
    assert history.backend() == "files"
    return tmp_path


def _record(contact_id="abc-123"):
    return {
        "contact_id": contact_id,
        "label": "test",
        "started_at": 1700000000.0,
        "ended_at": 1700000040.0,
        "max_anger": 85,
        "messages": [
            {"speaker": "customer", "text": "もしもし", "final": True,
             "ts": 1700000001.0, "item_id": "i1", "anger_score": 10},
        ],
    }


def test_save_load_roundtrip(file_backend):
    history.save_record(_record())
    got = history.load_record("abc-123")
    assert got["max_anger"] == 85
    assert got["messages"][0]["text"] == "もしもし"


def test_load_missing_returns_none(file_backend):
    assert history.load_record("no-such-call") is None


def test_hostile_contact_id_rejected(file_backend):
    """パストラバーサルの防止。contact_idはファイル名になるため。"""
    with pytest.raises(ValueError):
        history.load_record("../../etc/passwd")
    with pytest.raises(ValueError):
        history.load_record("a/b")


def test_list_records_sorted(file_backend):
    for cid, at in [("old", 100.0), ("new", 200.0)]:
        r = _record(cid)
        r["started_at"] = at
        history.save_record(r)
    got = history.list_records()
    assert [r["contact_id"] for r in got] == ["new", "old"]  # 新しい順


# ---- card: 判定に渡す本文の整形 ----


def test_card_render_skips_non_final_and_empty():
    msgs = [
        {"speaker": "customer", "text": "もしもし", "final": True},
        {"speaker": "customer", "text": "打鍵中", "final": False},
        {"speaker": "agent", "text": "", "final": True},
        {"speaker": "agent", "text": "伺っています", "final": True},
    ]
    body = card.render(msgs)
    assert body == "相手: もしもし\nオペレータ: 伺っています"


@pytest.mark.asyncio
async def test_make_card_empty_call_returns_none():
    """発話ゼロの呼ではAPIを呼ばずにNoneを返すこと(無駄な課金の防止)。"""
    assert await card.make_card([]) is None
    assert await card.make_card([{"speaker": "customer", "text": "", "final": True}]) is None
