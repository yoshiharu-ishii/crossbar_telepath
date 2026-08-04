"""呼ごとの記録(CDR)の永続化。交換機でいう呼詳細記録。

置き場は2通りで、`DATABASE_URL` があればPostgreSQL(db.py)、無ければ
`recordings/calls/<contact_id>.json` に書く。ファイル版を残してあるのは、
コンテナを立てずに開発できる状態を保つため。

音声そのものは storage.py(S3互換)の担当で、ここでは扱わない。
"""

from __future__ import annotations

import json
import logging
import re

import db
import storage
from config import CALLS_DIR

log = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def backend() -> str:
    return "postgres" if db.enabled() else "files"


def init() -> None:
    if db.enabled():
        db.init_db()
    else:
        log.info("DATABASE_URL 未設定のため呼の記録はファイルに書く: %s", CALLS_DIR)


def _path(contact_id: str):
    if not _SAFE_ID.fullmatch(contact_id):
        raise ValueError(f"不正なcontact_id: {contact_id!r}")
    return CALLS_DIR / f"{contact_id}.json"


def save_record(record: dict) -> None:
    """通話終了時に呼の記録を書く。"""
    if db.enabled():
        db.save_record(record)
        return
    CALLS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(record["contact_id"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    log.info("call record saved: %s (%d messages)", path.name, len(record.get("messages", [])))


def load_record(contact_id: str) -> dict | None:
    if db.enabled():
        rec = db.load_record(contact_id)
    else:
        path = _path(contact_id)
        rec = json.loads(path.read_text()) if path.exists() else None
    if rec is not None:
        rec["has_recording"] = storage.has_recording(contact_id)
    return rec


def list_records() -> list[dict]:
    """保存済みの呼の一覧(新しい順、メタのみ)。"""
    # 録音の有無は1回の問い合わせでまとめて調べる(1呼ずつHEADを打たない)
    recorded = storage.list_recorded_ids()

    if db.enabled():
        out = db.list_records()
    else:
        out = []
        if CALLS_DIR.exists():
            for p in CALLS_DIR.glob("*.json"):
                try:
                    rec = json.loads(p.read_text())
                except json.JSONDecodeError:
                    log.warning("壊れた呼記録を無視: %s", p.name)
                    continue
                out.append({
                    "contact_id": rec.get("contact_id"),
                    "label": rec.get("label"),
                    "customer_number": rec.get("customer_number"),
                    "started_at": rec.get("started_at"),
                    "ended_at": rec.get("ended_at"),
                    "max_anger": rec.get("max_anger"),
                    "message_count": len(rec.get("messages", [])),
                    # 会話一覧(明細)が使う列。DB側のlist_recordsと形を揃える
                    "summary": rec.get("summary") or (rec.get("card") or {}).get("summary"),
                    "owner_email": rec.get("owner_email"),
                    "card": rec.get("card"),
                    "live": False,
                })
        out.sort(key=lambda r: r.get("started_at") or 0, reverse=True)

    for r in out:
        r["has_recording"] = r["contact_id"] in recorded
    return out
