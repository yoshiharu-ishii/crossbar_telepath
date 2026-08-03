"""add call card column

Revision ID: d16f00e83b40
Revises: 730d3eb7e5c0
Create Date: 2026-08-03 12:50:11.294446

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd16f00e83b40'
down_revision: Union[str, Sequence[str], None] = '730d3eb7e5c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """通話カードのJSONを持つ列。

    summary(一行)とは別に、構造化された形のまま残す。外部システムへの
    受け渡し口を兼ねるため、요約に潰すと連携先で使えなくなる。
    """
    op.add_column("calls", sa.Column("card", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("calls", "card")
