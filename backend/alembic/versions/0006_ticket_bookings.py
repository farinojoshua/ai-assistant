"""ticket_bookings table

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "ticket_bookings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("partner_reference_number", sa.String(64), nullable=False),
        sa.Column("sams_customer_id", sa.String(36), nullable=False),
        sa.Column("sams_booking_id", sa.String(36), nullable=True),
        sa.Column("showtime_id", sa.String(36), nullable=False),
        sa.Column("cinema_name", sa.String(200), nullable=True),
        sa.Column("movie_name", sa.String(200), nullable=True),
        sa.Column("showtime_start", sa.String(40), nullable=True),
        sa.Column("seat_names", sa.String(200), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="booked"),
        sa.Column("payment_reference_number", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_ticket_bookings_phone", "ticket_bookings", ["phone"])
    op.create_index(
        "ix_ticket_bookings_partner_reference_number",
        "ticket_bookings",
        ["partner_reference_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("ticket_bookings")
