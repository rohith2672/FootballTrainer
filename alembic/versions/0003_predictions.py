"""Stored pre-kickoff predictions (live track record)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15

New table ``predictions``: one row per (league, match_day, home_team, away_team,
model_version). The API upserts it from /upcoming while now < kickoff and joins
it to ``matches`` on the natural key to settle results in /track-record.
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("fixture_id", sa.BigInteger(), nullable=True),
        sa.Column("league", sa.String(), nullable=False),
        sa.Column("match_day", sa.Date(), nullable=False),
        sa.Column("home_team", sa.String(), nullable=False),
        sa.Column("away_team", sa.String(), nullable=False),
        sa.Column("kickoff", sa.DateTime(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("home_win", sa.Float(), nullable=False),
        sa.Column("draw", sa.Float(), nullable=False),
        sa.Column("away_win", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "league", "match_day", "home_team", "away_team", "model_version",
            name="uq_predictions_fixture_model",
        ),
    )
    op.create_index("ix_predictions_kickoff", "predictions", ["kickoff"])


def downgrade() -> None:
    op.drop_index("ix_predictions_kickoff", table_name="predictions")
    op.drop_table("predictions")
