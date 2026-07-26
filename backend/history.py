"""呼ごとの記録の永続化。

交換機でいうCDR(呼詳細記録)+録音アーカイブ。1呼につき2ファイル:
- recordings/calls/<contact_id>.json  … メタ情報と確定発言(通話終了時に書く)
- recordings/calls/<contact_id>.mkv   … KVSから受けた生バイト列(実通話のみ)

録音は個人データなので recordings/ ごとgitignoreされている前提。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from config import CALLS_DIR

log = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _paths(contact_id: str) -> tuple[Path, Path]:
    if not _SAFE_ID.fullmatch(contact_id):
        raise ValueError(f"不正なcontact_id: {contact_id!r}")
    return CALLS_DIR / f"{contact_id}.json", CALLS_DIR / f"{contact_id}.mkv"


def save_record(record: dict) -> None:
    """通話終了時に呼の記録を書く。"""
    CALLS_DIR.mkdir(parents=True, exist_ok=True)
    path, _ = _paths(record["contact_id"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    log.info("call record saved: %s (%d messages)", path.name, len(record.get("messages", [])))


def recording_path(contact_id: str) -> Path:
    """録音MKVの置き場所(存在チェックは呼び出し側で)。"""
    _, mkv = _paths(contact_id)
    return mkv


def load_record(contact_id: str) -> dict | None:
    path, mkv = _paths(contact_id)
    if not path.exists():
        return None
    rec = json.loads(path.read_text())
    rec["has_recording"] = mkv.exists()
    return rec


def list_records() -> list[dict]:
    """保存済みの呼の一覧(新しい順、メタのみ)。"""
    if not CALLS_DIR.exists():
        return []
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
            "has_recording": p.with_suffix(".mkv").exists(),
            "live": False,
        })
    out.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    return out
