"""add check constraints to betting tables

Revision ID: a5203714459b
Revises: 5b056655411e
Create Date: 2026-06-02 23:36:16.249657

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5203714459b'
down_revision: Union[str, Sequence[str], None] = '5b056655411e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CHECKS = [
    ("odds_snapshots", "ck_odds_snapshot_odd", "odd > 1.0"),
    ("current_odds", "ck_current_odds_odd", "odd > 1.0"),
    ("predictions", "ck_prediction_prob", "probability >= 0 AND probability <= 1"),
    ("simulated_bets", "ck_simulated_bet_stake", "stake > 0"),
    ("simulated_bets", "ck_simulated_bet_odd", "odd_taken > 1.0"),
]


def upgrade() -> None:
    """Add CHECK constraints (SQLite recreates the table via batch mode)."""
    for table, name, condition in _CHECKS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_check_constraint(name, condition)


def downgrade() -> None:
    for table, name, _ in reversed(_CHECKS):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(name, type_="check")
