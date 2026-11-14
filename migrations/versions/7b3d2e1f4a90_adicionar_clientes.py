"""Adicionar clientes, endereços e vínculo nas entregas.

Revision ID: 7b3d2e1f4a90
Revises: 4f2c8a9b1d6e
"""

from alembic import op
import sqlalchemy as sa

revision = "7b3d2e1f4a90"
down_revision = "4f2c8a9b1d6e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clientes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("farmacia_id", sa.Integer(), nullable=False),
        sa.Column("cpf", sa.String(11), nullable=False),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("telefone", sa.String(11), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["farmacia_id"], ["farmacias.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("farmacia_id", "cpf", name="uq_clientes_farmacia_cpf"),
    )
    op.create_table(
        "enderecos_clientes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("endereco", sa.String(300), nullable=False),
        sa.Column("bairro", sa.String(120), nullable=False),
        sa.Column("complemento", sa.String(200), nullable=True),
        sa.Column("ultimo_uso", sa.DateTime(), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="CASCADE"),
    )
    with op.batch_alter_table("entregas") as batch_op:
        batch_op.add_column(sa.Column("cliente_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_entregas_cliente_id", "clientes", ["cliente_id"], ["id"], ondelete="RESTRICT")
    op.execute(
        "INSERT INTO clientes (farmacia_id, cpf, nome, telefone, criado_em, atualizado_em) "
        "SELECT farmacia_id, '00000000000', MAX(nome_cliente), MAX(telefone_cliente), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "FROM entregas GROUP BY farmacia_id"
    )
    op.execute(
        "UPDATE entregas SET cliente_id = (SELECT id FROM clientes WHERE clientes.farmacia_id = entregas.farmacia_id)"
    )
    with op.batch_alter_table("entregas") as batch_op:
        batch_op.alter_column("cliente_id", existing_type=sa.Integer(), nullable=False)


def downgrade():
    with op.batch_alter_table("entregas") as batch_op:
        batch_op.drop_constraint("fk_entregas_cliente_id", type_="foreignkey")
        batch_op.drop_column("cliente_id")
    op.drop_table("enderecos_clientes")
    op.drop_table("clientes")
