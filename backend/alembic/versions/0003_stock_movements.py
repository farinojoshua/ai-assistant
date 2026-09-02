"""stock_movements table

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "stock_movements",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("aksi", sa.String(16), nullable=False),
        sa.Column("product_sku", sa.String(100), nullable=False),
        sa.Column("product_nama", sa.String(200), nullable=False),
        sa.Column("delta_qty", sa.Integer(), nullable=False),
        sa.Column("qty_before", sa.Integer(), nullable=False),
        sa.Column("qty_after", sa.Integer(), nullable=False),
        sa.Column("gudang", sa.String(100), nullable=True),
        sa.Column("foto_file", sa.String(255), nullable=True),
        sa.Column("catatan", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_stock_movements_tenant_id", "stock_movements", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_table("stock_movements")
