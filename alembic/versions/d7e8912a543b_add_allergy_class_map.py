"""add_allergy_class_map

Revision ID: d7e8912a543b
Revises: 3ab039f2c817
Create Date: 2026-09-07 04:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd7e8912a543b'
down_revision: Union[str, Sequence[str], None] = '3ab039f2c817'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to include allergy_class_map."""
    op.create_table(
        'allergy_class_map',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('allergy_term', sa.Text(), nullable=False),
        sa.Column('rxclass_id', sa.Text(), nullable=False),
        sa.Column('rxclass_source', sa.Text(), nullable=False),
        sa.Column('cross_reactivity_note', sa.Text(), nullable=True),
        sa.Column('reference', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_allergy_class_map_allergy_term', 'allergy_class_map', ['allergy_term'], unique=False)
    op.create_index('idx_allergy_class_map_rxclass_id', 'allergy_class_map', ['rxclass_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_allergy_class_map_rxclass_id', table_name='allergy_class_map')
    op.drop_index('idx_allergy_class_map_allergy_term', table_name='allergy_class_map')
    op.drop_table('allergy_class_map')
