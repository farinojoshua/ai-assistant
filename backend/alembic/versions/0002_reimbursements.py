"""reimbursements table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "reimbursements",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("merchant", sa.String(200), nullable=False),
        sa.Column("tanggal_struk", sa.Date(), nullable=True),
        sa.Column("nominal", sa.Numeric(14, 2), nullable=False),
        sa.Column("mata_uang", sa.String(8), nullable=False, server_default="IDR"),
        sa.Column("kategori", sa.String(50), nullable=True),
        sa.Column("catatan", sa.Text(), nullable=True),
        sa.Column("struk_file", sa.String(255), nullable=True),
        sa.Column("struk_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("alasan", sa.Text(), nullable=True),
        sa.Column("decided_by", UUID, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_reimbursements_tenant_id", "reimbursements", ["tenant_id"]
    )
    op.create_index(
        "ix_reimbursements_dedup",
        "reimbursements",
        ["tenant_id", "merchant", "tanggal_struk", "nominal"],
    )


def downgrade() -> None:
    op.drop_table("reimbursements")
