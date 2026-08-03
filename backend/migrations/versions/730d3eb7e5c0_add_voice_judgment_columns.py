"""add voice judgment columns

Revision ID: 730d3eb7e5c0
Revises: 62ac05216b0a
Create Date: 2026-08-03 12:15:37.171505

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '730d3eb7e5c0'
down_revision: Union[str, Sequence[str], None] = '62ac05216b0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """声のトーン判定の結果を持つ列。

    テキスト判定(anger_*)を上書きせず別に持つ。両者が食い違った通話こそが
    「トーンでしか分からない怒り」の実例であり、突き合わせられる形で残す必要がある。
    """
    op.add_column("utterances", sa.Column("voice_score", sa.Integer(), nullable=True))
    op.add_column("utterances", sa.Column("voice_tone", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("utterances", "voice_tone")
    op.drop_column("utterances", "voice_score")
