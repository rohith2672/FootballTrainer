"""Multi-league match data: kickoff, shots, odds, source, natural key

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15

Changes to ``matches``:
  * new nullable columns: provider_id, kickoff, home/away_shots,
    home/away_shots_on_target, odds_home/draw/away, odds_source
  * new columns: source (NOT NULL, default 'fdorg'), match_day (NOT NULL after
    backfill = UTC day of ``date``)
  * ``id`` stays the primary key but becomes a pure surrogate key.  Existing
    rows keep their id (it was the football-data.org match id) and that value is
    copied to ``provider_id``, which is unique where not NULL.
  * unique natural key (league, match_day, home_team, away_team)

``id`` is BIGSERIAL already (migration 0001 created it as a single-column
integer primary key), but older inserts always supplied explicit ids, so the
sequence is advanced past MAX(id).  The same fix is applied to teams.id.
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("provider_id", sa.BigInteger(), nullable=True))
    op.add_column("matches", sa.Column("kickoff", sa.DateTime(), nullable=True))
    op.add_column("matches", sa.Column("match_day", sa.Date(), nullable=True))
    op.add_column("matches", sa.Column("home_shots", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("away_shots", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("home_shots_on_target", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("away_shots_on_target", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("odds_home", sa.Float(), nullable=True))
    op.add_column("matches", sa.Column("odds_draw", sa.Float(), nullable=True))
    op.add_column("matches", sa.Column("odds_away", sa.Float(), nullable=True))
    op.add_column("matches", sa.Column("odds_source", sa.String(), nullable=True))
    op.add_column(
        "matches",
        sa.Column("source", sa.String(), nullable=False, server_default="fdorg"),
    )

    # Backfill: every existing row came from football-data.org.
    # `date` is stored as naive UTC.
    op.execute(
        "UPDATE matches SET provider_id = id, kickoff = date, "
        "match_day = CAST(date AS DATE), source = 'fdorg'"
    )

    # The natural key must be unique before the constraint is added; keep the
    # lowest id of any duplicate group (same fixture listed twice).
    op.execute(
        """
        DELETE FROM matches a
        USING matches b
        WHERE a.id > b.id
          AND a.league = b.league
          AND a.match_day = b.match_day
          AND a.home_team = b.home_team
          AND a.away_team = b.away_team
        """
    )

    op.alter_column("matches", "match_day", existing_type=sa.Date(), nullable=False)

    op.create_unique_constraint("uq_matches_provider_id", "matches", ["provider_id"])
    op.create_unique_constraint(
        "uq_matches_natural_key",
        "matches",
        ["league", "match_day", "home_team", "away_team"],
    )

    # Make sure id/teams.id have working sequences positioned after existing rows.
    op.execute(
        """
        DO $$
        BEGIN
            IF pg_get_serial_sequence('matches', 'id') IS NULL THEN
                CREATE SEQUENCE matches_id_seq OWNED BY matches.id;
                ALTER TABLE matches ALTER COLUMN id SET DEFAULT nextval('matches_id_seq');
            END IF;
            IF pg_get_serial_sequence('teams', 'id') IS NULL THEN
                CREATE SEQUENCE teams_id_seq OWNED BY teams.id;
                ALTER TABLE teams ALTER COLUMN id SET DEFAULT nextval('teams_id_seq');
            END IF;
        END
        $$
        """
    )
    op.execute(
        "SELECT setval(pg_get_serial_sequence('matches', 'id'), "
        "COALESCE((SELECT MAX(id) FROM matches), 0) + 1, false)"
    )
    op.execute(
        "SELECT setval(pg_get_serial_sequence('teams', 'id'), "
        "COALESCE((SELECT MAX(id) FROM teams), 0) + 1, false)"
    )


def downgrade() -> None:
    # The id sequences created/advanced by upgrade() are harmless in the old
    # schema and are left in place.  Rows that were inserted after the upgrade
    # keep their surrogate ids (they have no football-data.org id to restore).
    op.drop_constraint("uq_matches_natural_key", "matches", type_="unique")
    op.drop_constraint("uq_matches_provider_id", "matches", type_="unique")

    for column in (
        "source",
        "odds_source",
        "odds_away",
        "odds_draw",
        "odds_home",
        "away_shots_on_target",
        "home_shots_on_target",
        "away_shots",
        "home_shots",
        "match_day",
        "kickoff",
        "provider_id",
    ):
        op.drop_column("matches", column)
