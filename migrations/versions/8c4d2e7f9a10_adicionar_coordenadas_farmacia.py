"""Adicionar coordenadas às farmácias.

Revision ID: 8c4d2e7f9a10
Revises: 7b3d2e1f4a90
"""

from alembic import op
import sqlalchemy as sa


revision = "8c4d2e7f9a10"
down_revision = "7b3d2e1f4a90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("farmacias", sa.Column("latitude", sa.Numeric(9, 6), nullable=True))
    op.add_column("farmacias", sa.Column("longitude", sa.Numeric(9, 6), nullable=True))


def downgrade():
    with op.batch_alter_table("farmacias") as batch_op:
        batch_op.drop_column("longitude")
        batch_op.drop_column("latitude")
