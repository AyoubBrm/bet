"""Add indexes used by the odds monitor and preserve SofaScore event data."""

from alembic import op


revision = "20260712_harden_odds_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE bet365_sofascore_mapping "
        "ADD COLUMN IF NOT EXISTS raw_event_data JSON"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_players_event_id "
        "ON players (event_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_player_shot_odds_player_id "
        "ON player_shot_odds (player_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_player_tackle_odds_player_id "
        "ON player_tackle_odds (player_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_player_tackle_odds_player_id")
    op.execute("DROP INDEX IF EXISTS ix_player_shot_odds_player_id")
    op.execute("DROP INDEX IF EXISTS ix_players_event_id")
