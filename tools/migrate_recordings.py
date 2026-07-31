"""ローカルに溜まった録音(recordings/calls/*.mkv)をオブジェクトストレージへ移す。

読み出しはオブジェクトストレージ→ローカルの順に探すので、移行しなくても
動きはする。このスクリプトは置き場を一本化したいときに使う。

使い方(backend/ から実行):
    S3_BUCKET=crossbar-telepath-recordings S3_ENDPOINT_URL=http://localhost:9000 \
    AWS_ACCESS_KEY_ID=crossbar AWS_SECRET_ACCESS_KEY=crossbar-dev-secret \
    uv run python ../tools/migrate_recordings.py [--delete-local]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import storage  # noqa: E402
from config import CALLS_DIR, S3_BUCKET  # noqa: E402


def main(delete_local: bool) -> None:
    if not storage.enabled():
        sys.exit("S3_BUCKET が未設定。移行先が無いので何もしない")

    files = sorted(CALLS_DIR.glob("*.mkv"))
    if not files:
        print("移行対象なし")
        return

    for path in files:
        contact_id = path.stem
        data = path.read_bytes()
        storage.put_recording(contact_id, data)
        print(f"→ {S3_BUCKET}: {contact_id} ({len(data):,} bytes)")
        if delete_local:
            path.unlink()
            print(f"  ローカル削除: {path.name}")

    print(f"完了: {len(files)}件")


if __name__ == "__main__":
    main("--delete-local" in sys.argv)
