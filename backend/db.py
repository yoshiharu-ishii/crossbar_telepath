"""呼の記録のRDB実装(開発はコンテナのPostgreSQL、本番はAurora PostgreSQL)。

同じエンジンをローカルで動かしているので、移行時に方言の差で驚くことがない。
`history.py` から呼ばれるだけで、他のモジュールはこのファイルを知らない。

時刻はDB内では timestamptz で持つ(「時間帯別の傾向」のような集計をSQLで
書けるようにするため)。外に出すときはUNIX秒に戻すので、画面やAPIから見た
データの形は JSON 実装のときと変わらない。
"""

from __future__ import annotations

import json

import logging
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    insert,
    select,
)

from config import BASE_DIR, DATABASE_URL

log = logging.getLogger(__name__)

metadata = MetaData()

calls = Table(
    "calls",
    metadata,
    Column("contact_id", String(64), primary_key=True),
    Column("label", Text),
    Column("customer_number", String(32)),
    # どのConnectインスタンス(=どの事業者の交換機)から来た呼か。
    # シグナリングで届いているので保存する。将来テナントを分ける日の足がかり
    Column("instance_arn", Text, index=True),
    Column("started_at", DateTime(timezone=True), nullable=False, index=True),
    Column("ended_at", DateTime(timezone=True)),
    # PH3で埋める。呼の一覧から「揉めた通話」を探せるようにするための列
    Column("max_anger", Integer),
    Column("summary", Text),
    Column("owner_email", Text),
    # 通話カードのJSON。外部システムへの受け渡し口なので、要約だけでなく
    # 構造化された形のまま残す(summary はその一行目を取り出したもの)
    Column("card", Text),
)

utterances = Table(
    "utterances",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "contact_id",
        String(64),
        ForeignKey("calls.contact_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("speaker", String(16), nullable=False),
    Column("item_id", String(64)),
    Column("text", Text),
    Column("ts", DateTime(timezone=True), nullable=False),
    # 録音内での発話区間(ミリ秒)。頭出し再生に使う
    Column("audio_start_ms", Integer),
    Column("audio_end_ms", Integer),
    # PH3で埋める
    Column("anger_score", Integer),
    Column("anger_reason", Text),
    # 声のトーンからの判定。テキストと食い違う通話こそが重要な事例になるため、
    # 上書きせず別の列に持つ
    Column("voice_score", Integer),
    Column("voice_tone", Text),
)


def enabled() -> bool:
    return bool(DATABASE_URL)


@lru_cache(maxsize=1)
def engine():
    # pool_pre_ping: Auroraのフェイルオーバ後に古い接続を掴んだままにしない
    return create_engine(DATABASE_URL, pool_pre_ping=True, future=True)


def init_db() -> None:
    """スキーマをマイグレーションで最新にする。

    create_all は既存テーブルに列を足せないので、スキーマの正はAlembicに一本化する。
    起動のたびに `alembic upgrade head` 相当を実行するので、開発では
    コンテナを起動し直すだけでスキーマが追いつく。
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    # アプリのログ設定をalembicのiniで上書きさせない
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    log.info("database ready: %s", DATABASE_URL.rsplit("@", 1)[-1])


def _to_dt(epoch: float | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, UTC) if epoch else None


def _to_epoch(dt: datetime | None) -> float | None:
    return dt.timestamp() if dt else None


def save_record(record: dict) -> None:
    """呼の記録を書く。再文字起こしでの上書きも想定して一度消してから入れる。"""
    contact_id = record["contact_id"]
    with engine().begin() as conn:
        conn.execute(delete(utterances).where(utterances.c.contact_id == contact_id))
        conn.execute(delete(calls).where(calls.c.contact_id == contact_id))
        conn.execute(
            insert(calls).values(
                contact_id=contact_id,
                label=record.get("label"),
                customer_number=record.get("customer_number"),
                instance_arn=record.get("instance_arn"),
                started_at=_to_dt(record.get("started_at")) or datetime.now(UTC),
                ended_at=_to_dt(record.get("ended_at")),
                max_anger=record.get("max_anger"),
                summary=record.get("summary"),
                owner_email=record.get("owner_email"),
                card=json.dumps(record["card"], ensure_ascii=False)
                if record.get("card")
                else None,
            )
        )
        rows = [
            {
                "contact_id": contact_id,
                "speaker": m.get("speaker"),
                "item_id": m.get("item_id"),
                "text": m.get("text"),
                "ts": _to_dt(m.get("ts")) or datetime.now(UTC),
                "audio_start_ms": m.get("audio_start_ms"),
                "audio_end_ms": m.get("audio_end_ms"),
                "anger_score": m.get("anger_score"),
                "anger_reason": m.get("anger_reason"),
                "voice_score": m.get("voice_score"),
                "voice_tone": m.get("voice_tone"),
            }
            for m in record.get("messages", [])
        ]
        if rows:
            conn.execute(insert(utterances), rows)
    log.info("call record saved: %s (%d messages)", contact_id, len(rows))


def _message_dict(row) -> dict:
    msg = {
        "type": "transcript",
        "speaker": row.speaker,
        "item_id": row.item_id,
        "text": row.text,
        "final": True,
        "ts": _to_epoch(row.ts),
    }
    if row.audio_start_ms is not None:
        msg["audio_start_ms"] = row.audio_start_ms
        msg["audio_end_ms"] = row.audio_end_ms
    if row.anger_score is not None:
        msg["anger_score"] = row.anger_score
        msg["anger_reason"] = row.anger_reason
    if row.voice_score is not None:
        msg["voice_score"] = row.voice_score
        msg["voice_tone"] = row.voice_tone
    return msg


def load_record(contact_id: str) -> dict | None:
    with engine().connect() as conn:
        call = conn.execute(select(calls).where(calls.c.contact_id == contact_id)).one_or_none()
        if call is None:
            return None
        msgs = conn.execute(
            select(utterances)
            .where(utterances.c.contact_id == contact_id)
            .order_by(utterances.c.ts, utterances.c.id)
        ).all()
    return {
        "contact_id": call.contact_id,
        "label": call.label,
        "customer_number": call.customer_number,
        "instance_arn": call.instance_arn,
        "started_at": _to_epoch(call.started_at),
        "ended_at": _to_epoch(call.ended_at),
        "max_anger": call.max_anger,
        "summary": call.summary,
        "owner_email": call.owner_email,
        "card": json.loads(call.card) if call.card else None,
        "message_count": len(msgs),
        "live": False,
        "messages": [_message_dict(m) for m in msgs],
    }


def list_records() -> list[dict]:
    """呼の一覧(新しい順、メタのみ)。発話数は集計で取る。"""
    counts = (
        select(utterances.c.contact_id, func.count().label("n"))
        .group_by(utterances.c.contact_id)
        .subquery()
    )
    stmt = (
        select(calls, func.coalesce(counts.c.n, 0).label("message_count"))
        .outerjoin(counts, calls.c.contact_id == counts.c.contact_id)
        .order_by(calls.c.started_at.desc())
    )
    with engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [
        {
            "contact_id": r.contact_id,
            "label": r.label,
            "customer_number": r.customer_number,
            "instance_arn": r.instance_arn,
            "started_at": _to_epoch(r.started_at),
            "ended_at": _to_epoch(r.ended_at),
            "max_anger": r.max_anger,
            "message_count": r.message_count,
            "live": False,
        }
        for r in rows
    ]
