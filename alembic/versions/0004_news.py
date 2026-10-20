"""Publisher headline cache and hourly refresh state.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "news_articles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("publisher", sa.String(80), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source", "url", name="uq_news_source_url"),
    )
    op.create_index("ix_news_published_at", "news_articles", ["published_at"])
    op.create_table(
        "news_feed_states",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("etag", sa.String(), nullable=True),
        sa.Column("last_modified", sa.String(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("next_check_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("news_feed_states")
    op.drop_index("ix_news_published_at", table_name="news_articles")
    op.drop_table("news_articles")
