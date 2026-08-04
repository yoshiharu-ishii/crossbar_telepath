"""add owner email to calls

Revision ID: dfe5c3ee3080
Revises: d16f00e83b40
Create Date: 2026-08-04 12:12:22.239796

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dfe5c3ee3080'
down_revision: Union[str, Sequence[str], None] = 'd16f00e83b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """担当者(挙手方式)。割り当ての正本=自前DBの実体。"""
    op.add_column("calls", sa.Column("owner_email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("calls", "owner_email")
