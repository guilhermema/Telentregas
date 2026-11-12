from datetime import datetime, time, timedelta
from decimal import Decimal

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app.decorators import role_required
from app.extensions import db
from app.forms import EntregaForm
from app.models import BairroPreco, Entrega, Farmacia

farmacia_bp = Blueprint("farmacia", __name__)


@farmacia_bp.get("/")
@role_required("farmacia")
def dashboard():
    farmacia = _farmacia_logada()
    bairros = _bairros_da_farmacia(farmacia.id)
    form = _formulario(bairros)
    return render_template(
        "farmacia/dashboard.html",
        farmacia=farmacia,
        form=form,
        bairros=bairros,
        taxas={bairro.bairro: f"R$ {bairro.valor_taxa:.2f}" for bairro in bairros},
    )


@farmacia_bp.post("/entregas/nova")
@role_required("farmacia")
def nova_entrega():
    farmacia = _farmacia_logada()
    bairros = _bairros_da_farmacia(farmacia.id)
    form = _formulario(bairros)

    if not bairros:
        flash("Bairro não cadastrado. Solicite à Central", "error")
        return redirect(url_for("farmacia.dashboard"))

    if form.validate_on_submit():
        bairro_preco = BairroPreco.query.filter_by(
            farmacia_id=farmacia.id, bairro=form.bairro_entrega.data
        ).first()
        if bairro_preco is None:
            flash("Bairro não cadastrado. Solicite à Central", "error")
            return redirect(url_for("farmacia.dashboard"))

        entrega = Entrega(
            farmacia_id=farmacia.id,
            nome_cliente=form.nome_cliente.data.strip(),
            telefone_cliente=_telefone_normalizado(form.telefone_cliente.data),
            endereco_entrega=form.endereco_entrega.data.strip(),
            bairro_entrega=bairro_preco.bairro,
            valor_taxa=Decimal(bairro_preco.valor_taxa),
            precisa_troco=form.precisa_troco.data,
            valor_troco=form.valor_troco.data,
            usa_maquininha=form.usa_maquininha.data,
            observacoes=(form.observacoes.data or "").strip() or None,
        )
        db.session.add(entrega)
        db.session.commit()
        from app.push import notificar_motoboys

        notificar_motoboys(entrega)
        flash("Entrega cadastrada com sucesso.", "success")
        return redirect(url_for("farmacia.dashboard"))

    flash("Corrija os campos destacados e tente novamente.", "error")
    return render_template(
        "farmacia/dashboard.html",
        farmacia=farmacia,
        form=form,
        bairros=bairros,
        taxas={bairro.bairro: f"R$ {bairro.valor_taxa:.2f}" for bairro in bairros},
    ), 400


@farmacia_bp.get("/api/andamento")
@role_required("farmacia")
def andamento_json():
    farmacia = _farmacia_logada()
    entregas = _entregas_andamento(farmacia.id)
    return jsonify({"entregas": [_entrega_json(entrega) for entrega in entregas]})


@farmacia_bp.get("/historico")
@role_required("farmacia")
def historico():
    farmacia = _farmacia_logada()
    page = request.args.get("page", 1, type=int)
    data_de = _parse_date(request.args.get("de"))
    data_ate = _parse_date(request.args.get("ate"))
    query = Entrega.query.filter(
        Entrega.farmacia_id == farmacia.id,
        Entrega.status.in_(("entregue", "cancelada")),
    )
    if data_de:
        query = query.filter(Entrega.data_criacao >= datetime.combine(data_de, time.min))
    if data_ate:
        query = query.filter(Entrega.data_criacao < datetime.combine(data_ate + timedelta(days=1), time.min))

    pagination = query.order_by(Entrega.data_criacao.desc()).paginate(page=page, per_page=20, error_out=False)
    total_query = Entrega.query.filter(
        Entrega.farmacia_id == farmacia.id,
        Entrega.status == "entregue",
    )
    if data_de:
        total_query = total_query.filter(Entrega.data_criacao >= datetime.combine(data_de, time.min))
    if data_ate:
        total_query = total_query.filter(Entrega.data_criacao < datetime.combine(data_ate + timedelta(days=1), time.min))
    total = sum((entrega.valor_taxa for entrega in total_query.all()), Decimal("0.00"))

    return render_template(
        "farmacia/historico.html",
        farmacia=farmacia,
        pagination=pagination,
        total=total,
        data_de=request.args.get("de", ""),
        data_ate=request.args.get("ate", ""),
    )


def _farmacia_logada() -> Farmacia:
    farmacia = Farmacia.query.filter_by(user_id=current_user.id).first()
    if farmacia is None:
        abort(404)
    return farmacia


def _bairros_da_farmacia(farmacia_id: int) -> list[BairroPreco]:
    return BairroPreco.query.filter_by(farmacia_id=farmacia_id).order_by(BairroPreco.bairro).all()


def _formulario(bairros: list[BairroPreco]) -> EntregaForm:
    form = EntregaForm()
    form.bairro_entrega.choices = [(bairro.bairro, bairro.bairro) for bairro in bairros]
    return form


def _entregas_andamento(farmacia_id: int) -> list[Entrega]:
    return Entrega.query.filter(
        Entrega.farmacia_id == farmacia_id,
        Entrega.status.in_(("pendente", "aceita", "coletada")),
    ).order_by(Entrega.data_criacao.desc()).all()


def _telefone_normalizado(telefone: str) -> str:
    return "".join(char for char in telefone if char.isdigit())


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _entrega_json(entrega: Entrega) -> dict:
    return {
        "id": entrega.id,
        "status": entrega.status,
        "nome_cliente": entrega.nome_cliente,
        "bairro": entrega.bairro_entrega,
        "valor_taxa": f"{entrega.valor_taxa:.2f}",
        "motoboy": entrega.motoboy.nome if entrega.motoboy else None,
        "data_criacao": entrega.data_criacao.isoformat(),
        "data_aceite": entrega.data_aceite.isoformat() if entrega.data_aceite else None,
        "data_coleta": entrega.data_coleta.isoformat() if entrega.data_coleta else None,
    }
