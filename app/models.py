from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Numeric, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True, server_default="true")
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    farmacia = db.relationship(
        "Farmacia", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    motoboy = db.relationship(
        "Motoboy", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    push_subscriptions = db.relationship(
        "PushSubscription", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'farmacia', 'motoboy')", name="ck_users_role"),
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self) -> bool:
        return self.ativo


class Farmacia(db.Model):
    __tablename__ = "farmacias"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    razao_social = db.Column(db.String(200), nullable=False)
    cnpj_cpf = db.Column(db.String(18), nullable=False)
    endereco_fixo = db.Column(db.String(300), nullable=False)
    cidade = db.Column(db.String(100), nullable=False, default="Itajaí", server_default="Itajaí")
    uf = db.Column(db.String(2), nullable=False, default="SC", server_default="SC")
    telefone = db.Column(db.String(30), nullable=False)
    responsavel_financeiro = db.Column(db.String(150), nullable=False)

    user = db.relationship("User", back_populates="farmacia")
    bairros_precos = db.relationship(
        "BairroPreco", back_populates="farmacia", cascade="all, delete-orphan"
    )
    entregas = db.relationship("Entrega", back_populates="farmacia")


class BairroPreco(db.Model):
    __tablename__ = "bairros_precos"

    id = db.Column(db.Integer, primary_key=True)
    farmacia_id = db.Column(
        db.Integer, db.ForeignKey("farmacias.id", ondelete="CASCADE"), nullable=False
    )
    bairro = db.Column(db.String(120), nullable=False)
    valor_taxa = db.Column(Numeric(10, 2), nullable=False)

    farmacia = db.relationship("Farmacia", back_populates="bairros_precos")

    __table_args__ = (
        UniqueConstraint("farmacia_id", "bairro", name="uq_bairros_precos_farmacia_bairro"),
        CheckConstraint("valor_taxa >= 0", name="ck_bairros_precos_valor_taxa_nonnegative"),
    )


class Motoboy(db.Model):
    __tablename__ = "motoboys"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    nome = db.Column(db.String(150), nullable=False)
    telefone = db.Column(db.String(30), nullable=False)
    placa_moto = db.Column(db.String(10), nullable=False)

    user = db.relationship("User", back_populates="motoboy")
    entregas = db.relationship("Entrega", back_populates="motoboy")


class Entrega(db.Model):
    __tablename__ = "entregas"

    id = db.Column(db.Integer, primary_key=True)
    farmacia_id = db.Column(
        db.Integer, db.ForeignKey("farmacias.id", ondelete="RESTRICT"), nullable=False
    )
    motoboy_id = db.Column(
        db.Integer, db.ForeignKey("motoboys.id", ondelete="RESTRICT"), nullable=True
    )
    nome_cliente = db.Column(db.String(150), nullable=False)
    telefone_cliente = db.Column(db.String(30), nullable=False)
    endereco_entrega = db.Column(db.String(300), nullable=False)
    bairro_entrega = db.Column(db.String(120), nullable=False)
    valor_taxa = db.Column(Numeric(10, 2), nullable=False)
    precisa_troco = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    valor_troco = db.Column(Numeric(10, 2), nullable=True)
    usa_maquininha = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    observacoes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pendente", server_default="pendente")
    motivo_cancelamento = db.Column(db.Text, nullable=True)
    data_criacao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    data_aceite = db.Column(db.DateTime, nullable=True)
    data_coleta = db.Column(db.DateTime, nullable=True)
    data_entrega = db.Column(db.DateTime, nullable=True)
    data_cancelamento = db.Column(db.DateTime, nullable=True)

    farmacia = db.relationship("Farmacia", back_populates="entregas")
    motoboy = db.relationship("Motoboy", back_populates="entregas")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pendente', 'aceita', 'coletada', 'entregue', 'cancelada')",
            name="ck_entregas_status",
        ),
        CheckConstraint("valor_taxa >= 0", name="ck_entregas_valor_taxa_nonnegative"),
        CheckConstraint(
            "valor_troco IS NULL OR valor_troco >= 0",
            name="ck_entregas_valor_troco_nonnegative",
        ),
        CheckConstraint(
            "(precisa_troco = false AND valor_troco IS NULL) OR "
            "(precisa_troco = true AND valor_troco IS NOT NULL AND valor_troco >= 0)",
            name="ck_entregas_troco_consistente",
        ),
    )


class PushSubscription(db.Model):
    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    user_agent = db.Column(db.String(500), nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", back_populates="push_subscriptions")
