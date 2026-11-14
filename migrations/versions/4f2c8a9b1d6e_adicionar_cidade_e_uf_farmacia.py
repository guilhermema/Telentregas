"""Adicionar cidade e UF às farmácias.

Revision ID: 4f2c8a9b1d6e
Revises: a571c9aba857
"""

from alembic import op
import sqlalchemy as sa


revision = "4f2c8a9b1d6e"
down_revision = "a571c9aba857"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("farmacias", sa.Column("cidade", sa.String(length=100), nullable=True))
    op.add_column("farmacias", sa.Column("uf", sa.String(length=2), nullable=True))
    op.execute("UPDATE farmacias SET cidade = 'Itajaí' WHERE cidade IS NULL")
    op.execute("UPDATE farmacias SET uf = 'SC' WHERE uf IS NULL")
    with op.batch_alter_table("farmacias") as batch_op:
        batch_op.alter_column("cidade", existing_type=sa.String(length=100), nullable=False)
        batch_op.alter_column("uf", existing_type=sa.String(length=2), nullable=False)


def downgrade():
    with op.batch_alter_table("farmacias") as batch_op:
        batch_op.drop_column("uf")
        batch_op.drop_column("cidade")
