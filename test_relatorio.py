"""Teste isolado do relatório PDF da Etapa 6."""

from datetime import datetime
from decimal import Decimal

from app import create_app
from app.extensions import db
from app.models import Cliente, Entrega, Farmacia, User
from app.report import cancelled_data, report_data, subtotal_data, summary_data


class TestConfig:
    SECRET_KEY = "test"
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


app = create_app(TestConfig)
with app.app_context():
    db.create_all()
    admin = User(username="admin-relatorio", role="admin", ativo=True)
    admin.set_password("senha1234")
    farmacia = Farmacia(
        user=admin,
        razao_social="Farmácia Relatório",
        cnpj_cpf="00.000.000/0001-00",
        endereco_fixo="Rua A, 10",
        telefone="11999999999",
        responsavel_financeiro="Financeiro",
    )
    db.session.add(farmacia)
    db.session.flush()
    cliente = Cliente(
        farmacia_id=farmacia.id,
        cpf="52998224725",
        nome="Cliente Teste",
        telefone="11999999999",
    )
    db.session.add(cliente)
    db.session.flush()
    entregas = [
        Entrega(
            farmacia_id=farmacia.id,
            cliente_id=cliente.id,
            nome_cliente="Ana Silva",
            telefone_cliente="11999999999",
            endereco_entrega="Rua",
            bairro_entrega="Centro",
            valor_taxa=Decimal("8.50"),
            status="entregue",
            data_entrega=datetime(2026, 11, 12, 15, 0),
        ),
        Entrega(
            farmacia_id=farmacia.id,
            cliente_id=cliente.id,
            nome_cliente="Bruno Souza",
            telefone_cliente="11999999999",
            endereco_entrega="Rua",
            bairro_entrega="Centro",
            valor_taxa=Decimal("8.50"),
            status="entregue",
            data_entrega=datetime(2026, 11, 12, 16, 0),
        ),
        Entrega(
            farmacia_id=farmacia.id,
            cliente_id=cliente.id,
            nome_cliente="Carla Lima",
            telefone_cliente="11999999999",
            endereco_entrega="Rua",
            bairro_entrega="Jardins",
            valor_taxa=Decimal("12.00"),
            status="entregue",
            data_entrega=datetime(2026, 11, 13, 16, 0),
        ),
        Entrega(
            farmacia_id=farmacia.id,
            cliente_id=cliente.id,
            nome_cliente="Cancelada",
            telefone_cliente="11999999999",
            endereco_entrega="Rua",
            bairro_entrega="Centro",
            valor_taxa=Decimal("99.00"),
            status="cancelada",
            motivo_cancelamento="Cliente desistiu",
            data_cancelamento=datetime(2026, 11, 12, 17, 0),
        ),
    ]
    db.session.add_all(entregas)
    db.session.commit()
    entregues = (
        Entrega.query.filter_by(farmacia_id=farmacia.id, status="entregue")
        .order_by(Entrega.data_entrega)
        .all()
    )
    rows, total = report_data(entregues)
    canceladas = Entrega.query.filter_by(farmacia_id=farmacia.id, status="cancelada").all()
    resumo = summary_data(entregues, canceladas)
    assert total == Decimal("29.00")
    assert resumo == {
        "entregues": 3,
        "canceladas": 1,
        "media": Decimal("9.666666666666666666666666667"),
        "total": Decimal("29.00"),
    }
    assert cancelled_data(canceladas)[0]["taxa"] == Decimal("99.00")
    assert [(item["bairro"], item["quantidade"], item["valor"]) for item in subtotal_data(entregues)] == [
        ("Centro", 2, Decimal("17.00")),
        ("Jardins", 1, Decimal("12.00")),
    ]
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(admin.id)
        session["_fresh"] = True
    response = client.get("/central/clientes/1/relatorio.pdf?de=2026-11-12&ate=2026-11-13&detalhado=1")
    assert response.status_code == 200
    assert response.content_type == "application/pdf"
    assert response.data.startswith(b"%PDF")
    assert b"29.00" not in response.data
print("relatorio PDF OK: resumo 3 entregues/1 cancelada; media R$ 9,67; total R$ 29,00; cancelada excluida")
