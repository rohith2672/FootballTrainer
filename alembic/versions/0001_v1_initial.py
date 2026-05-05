"""V1 initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-05
"""

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("league", sa.String(), nullable=False),
        sa.UniqueConstraint("name", name="uq_teams_name"),
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("home_team", sa.String(), nullable=False),
        sa.Column("away_team", sa.String(), nullable=False),
        sa.Column("home_goals", sa.Integer(), nullable=True),
        sa.Column("away_goals", sa.Integer(), nullable=True),
        sa.Column("result", sa.String(1), nullable=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("league", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("matches")
    op.drop_table("teams")
