"""Adicionar auditoria da devolução à praça.

Revision ID: 9d5e3f8a1b20
Revises: 8c4d2e7f9a10
"""

from alembic import op
import sqlalchemy as sa


revision = "9d5e3f8a1b20"
down_revision = "8c4d2e7f9a10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("entregas", sa.Column("motivo_devolucao", sa.Text(), nullable=True))
    op.add_column("entregas", sa.Column("devolvida_em", sa.DateTime(), nullable=True))
    op.add_column(
        "entregas",
        sa.Column("devolvida_por_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "entregas",
        sa.Column("motoboy_anterior_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_entregas_devolvida_por_user_id",
        "entregas",
        "users",
        ["devolvida_por_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_entregas_motoboy_anterior_id",
        "entregas",
        "motoboys",
        ["motoboy_anterior_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_entregas_motoboy_anterior_id", "entregas", type_="foreignkey")
    op.drop_constraint("fk_entregas_devolvida_por_user_id", "entregas", type_="foreignkey")
    with op.batch_alter_table("entregas") as batch_op:
        batch_op.drop_column("devolvida_por_user_id")
        batch_op.drop_column("motoboy_anterior_id")
        batch_op.drop_column("devolvida_em")
        batch_op.drop_column("motivo_devolucao")
