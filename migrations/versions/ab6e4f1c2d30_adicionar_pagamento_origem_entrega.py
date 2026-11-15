"""Adicionar pagamento e origem da entrega.

Revision ID: ab6e4f1c2d30
Revises: 9d5e3f8a1b20
"""

from alembic import op
import sqlalchemy as sa


revision = "ab6e4f1c2d30"
down_revision = "9d5e3f8a1b20"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("entregas", sa.Column("forma_pagamento", sa.String(length=20), nullable=True))
    op.add_column("entregas", sa.Column("valor_cobrar", sa.Numeric(10, 2), nullable=True))
    op.add_column("entregas", sa.Column("criada_por_central", sa.Boolean(), nullable=True))
    op.execute(
        "UPDATE entregas SET forma_pagamento = CASE "
        "WHEN usa_maquininha THEN 'cartao' ELSE 'dinheiro' END"
    )
    op.execute("UPDATE entregas SET criada_por_central = false WHERE criada_por_central IS NULL")
    op.execute("UPDATE entregas SET usa_maquininha = true WHERE forma_pagamento = 'cartao'")
    with op.batch_alter_table("entregas") as batch_op:
        batch_op.alter_column("forma_pagamento", existing_type=sa.String(length=20), nullable=False)
        batch_op.alter_column("criada_por_central", existing_type=sa.Boolean(), nullable=False)
        batch_op.create_check_constraint(
            "ck_entregas_forma_pagamento",
            "forma_pagamento IN ('pix', 'dinheiro', 'cartao', 'convenio', 'ja_pago')",
        )


def downgrade():
    with op.batch_alter_table("entregas") as batch_op:
        batch_op.drop_constraint("ck_entregas_forma_pagamento", type_="check")
        batch_op.drop_column("criada_por_central")
        batch_op.drop_column("valor_cobrar")
        batch_op.drop_column("forma_pagamento")
