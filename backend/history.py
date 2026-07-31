"""呼ごとの記録(CDR)の永続化。

交換機でいう呼詳細記録。1呼につき `recordings/calls/<contact_id>.json` に
メタ情報(発信者番号・開始/終了時刻)と確定発言を書く。
音声そのものは storage.py(S3互換)の担当で、ここでは扱わない。

PH3でPostgreSQLへ移す予定。そのとき差し替えるのはこのファイルの中身だけで、
save_record / load_record / list_records のインターフェースは変えない。
"""

from __future__ import annotations

import json
import logging
import re

import storage
from config import CALLS_DIR

log = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _path(contact_id: str):
    if not _SAFE_ID.fullmatch(contact_id):
        raise ValueError(f"不正なcontact_id: {contact_id!r}")
    return CALLS_DIR / f"{contact_id}.json"


def save_record(record: dict) -> None:
    """通話終了時に呼の記録を書く。"""
    CALLS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(record["contact_id"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    log.info("call record saved: %s (%d messages)", path.name, len(record.get("messages", [])))


def load_record(contact_id: str) -> dict | None:
    path = _path(contact_id)
    if not path.exists():
        return None
    rec = json.loads(path.read_text())
    rec["has_recording"] = storage.has_recording(contact_id)
    return rec


def list_records() -> list[dict]:
    """保存済みの呼の一覧(新しい順、メタのみ)。"""
    if not CALLS_DIR.exists():
        return []
    # 録音の有無は1回の問い合わせでまとめて調べる(1呼ずつHEADを打たない)
    recorded = storage.list_recorded_ids()
    out = []
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
            "message_count": len(rec.get("messages", [])),
            "has_recording": rec.get("contact_id") in recorded,
            "live": False,
        })
    out.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    return out
