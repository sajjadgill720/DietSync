"""initial_schema

Revision ID: 3ab039f2c817
Revises: 
Create Date: 2026-09-04 16:17:45.579943

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3ab039f2c817'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Enable PostgreSQL extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

    # 1. drugs table
    op.create_table(
        'drugs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('brand_name', sa.Text(), nullable=False),
        sa.Column('drap_reg_no', sa.Text(), nullable=True),
        sa.Column('dosage_form', sa.Text(), nullable=True),
        sa.Column('company_name', sa.Text(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'idx_drugs_brand_name',
        'drugs',
        ['brand_name'],
        unique=False,
        postgresql_using='gin',
        postgresql_ops={'brand_name': 'gin_trgm_ops'}
    )

    # 2. drug_ingredients table
    op.create_table(
        'drug_ingredients',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('drug_id', sa.Integer(), nullable=False),
        sa.Column('generic_name', sa.Text(), nullable=False),
        sa.Column('dose', sa.Text(), nullable=True),
        sa.Column('rxcui', sa.Text(), nullable=True),
        sa.Column('rxnorm_name', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['drug_id'], ['drugs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_drug_ingredients_drug_id', 'drug_ingredients', ['drug_id'], unique=False)
    op.create_index('idx_drug_ingredients_rxcui', 'drug_ingredients', ['rxcui'], unique=False)

    # 3. fda_labels table
    op.create_table(
        'fda_labels',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('rxcui', sa.Text(), nullable=False),
        sa.Column('rxnorm_name', sa.Text(), nullable=False),
        sa.Column('drug_interactions', sa.Text(), nullable=True),
        sa.Column('warnings', sa.Text(), nullable=True),
        sa.Column('boxed_warning', sa.Text(), nullable=True),
        sa.Column('raw_response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rxcui')
    )

    # 4. interaction_jobs table
    op.create_table(
        'interaction_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('drug_a_id', sa.Integer(), nullable=True),
        sa.Column('drug_b_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'processing', 'done', 'failed')", name='check_interaction_jobs_status'),
        sa.ForeignKeyConstraint(['drug_a_id'], ['drugs.id'], ),
        sa.ForeignKeyConstraint(['drug_b_id'], ['drugs.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('interaction_jobs')
    op.drop_table('fda_labels')
    op.drop_index('idx_drug_ingredients_rxcui', table_name='drug_ingredients')
    op.drop_index('idx_drug_ingredients_drug_id', table_name='drug_ingredients')
    op.drop_table('drug_ingredients')
    op.drop_index('idx_drugs_brand_name', table_name='drugs', postgresql_using='gin', postgresql_ops={'brand_name': 'gin_trgm_ops'})
    op.drop_table('drugs')
