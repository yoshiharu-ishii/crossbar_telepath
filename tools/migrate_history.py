"""ファイルに溜まった呼の記録(recordings/calls/*.json)をDBへ移す。

使い方(backend/ から実行):
    DATABASE_URL=postgresql+psycopg://crossbar:crossbar-dev-secret@localhost:5433/crossbar \
    uv run python ../tools/migrate_history.py [--delete-local]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import db  # noqa: E402
from config import CALLS_DIR  # noqa: E402


def main(delete_local: bool) -> None:
    if not db.enabled():
        sys.exit("DATABASE_URL が未設定。移行先が無いので何もしない")

    db.init_db()
    files = sorted(CALLS_DIR.glob("*.json"))
    if not files:
        print("移行対象なし")
        return

    for path in files:
        record = json.loads(path.read_text())
        db.save_record(record)
        print(f"→ DB: {record['contact_id']} ({len(record.get('messages', []))} messages)")
        if delete_local:
            path.unlink()
            print(f"  ローカル削除: {path.name}")

    print(f"完了: {len(files)}件")


if __name__ == "__main__":
    main("--delete-local" in sys.argv)
