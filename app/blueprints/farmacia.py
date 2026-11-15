from datetime import datetime, time, timedelta
from decimal import Decimal

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app.decorators import role_required
from app.extensions import db
from app.forms import EntregaForm
from app.models import BairroPreco, Cliente, EnderecoCliente, Entrega, Farmacia
from app.report import brl, delivered_query, history_query, parse_report_dates
from app.utils.validators import mask_cpf, normalize_cpf, normalize_phone, normalize_text

farmacia_bp = Blueprint("farmacia", __name__)
_busca_rate_limit: dict[str, list[datetime]] = {}


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
        try:
            criar_entrega(farmacia, form)
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("farmacia.dashboard"))
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


@farmacia_bp.get("/api/clientes/buscar")
@role_required("farmacia")
def buscar_cliente():
    farmacia = _farmacia_logada()
    agora = datetime.utcnow()
    chave = request.remote_addr or "desconhecido"
    tentativas = [momento for momento in _busca_rate_limit.get(chave, []) if (agora - momento).total_seconds() < 60]
    if len(tentativas) >= 30:
        return jsonify({"mensagem": "Muitas consultas. Tente novamente em instantes."}), 429
    tentativas.append(agora)
    _busca_rate_limit[chave] = tentativas
    try:
        cpf = normalize_cpf(request.args.get("cpf", ""))
    except ValueError:
        return jsonify({"encontrado": False}), 400
    cliente = Cliente.query.filter_by(farmacia_id=farmacia.id, cpf=cpf).first()
    if cliente is None:
        return jsonify({"encontrado": False, "mensagem": "Cliente novo"})
    enderecos = sorted((item for item in cliente.enderecos if item.ativo), key=lambda item: item.ultimo_uso, reverse=True)
    return jsonify({
        "encontrado": True,
        "cpf": mask_cpf(cliente.cpf),
        "nome": cliente.nome,
        "telefone": cliente.telefone,
        "enderecos": [
            {"id": item.id, "endereco": item.endereco, "bairro": item.bairro, "complemento": item.complemento}
            for item in enderecos
        ],
    })


@farmacia_bp.get("/clientes")
@role_required("farmacia")
def clientes():
    farmacia = _farmacia_logada()
    busca = request.args.get("busca", "").strip()
    query = Cliente.query.filter_by(farmacia_id=farmacia.id)
    if busca:
        termo = f"%{busca}%"
        query = query.filter((Cliente.nome.ilike(termo)) | (Cliente.telefone.ilike(termo)) | (Cliente.cpf.ilike(termo)))
    return render_template("farmacia/clientes.html", clientes=query.order_by(Cliente.nome).all(), busca=busca, mask_cpf=mask_cpf)


@farmacia_bp.post("/clientes/<int:cliente_id>/editar")
@role_required("farmacia")
def editar_cliente(cliente_id: int):
    farmacia = _farmacia_logada()
    cliente = Cliente.query.filter_by(id=cliente_id, farmacia_id=farmacia.id).first_or_404()
    try:
        cliente.cpf = normalize_cpf(request.form.get("cpf", cliente.cpf))
        cliente.telefone = normalize_phone(request.form.get("telefone", cliente.telefone))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("farmacia.clientes"))
    cliente.nome = request.form.get("nome", "").strip()
    if not cliente.nome or Cliente.query.filter(
        Cliente.farmacia_id == farmacia.id, Cliente.cpf == cliente.cpf, Cliente.id != cliente.id
    ).first():
        flash("Nome obrigatório ou CPF já cadastrado nesta farmácia.", "error")
        return redirect(url_for("farmacia.clientes"))
    db.session.commit()
    flash("Cliente atualizado.", "success")
    return redirect(url_for("farmacia.clientes"))


@farmacia_bp.post("/clientes/<int:cliente_id>/enderecos")
@role_required("farmacia")
def adicionar_endereco(cliente_id: int):
    farmacia = _farmacia_logada()
    cliente = Cliente.query.filter_by(id=cliente_id, farmacia_id=farmacia.id).first_or_404()
    endereco = request.form.get("endereco", "").strip()
    bairro = request.form.get("bairro", "").strip()
    if not endereco or not bairro:
        flash("Endereço e bairro são obrigatórios.", "error")
        return redirect(url_for("farmacia.clientes"))
    existente = next((item for item in cliente.enderecos if normalize_text(item.endereco) == normalize_text(endereco) and normalize_text(item.bairro) == normalize_text(bairro)), None)
    if existente:
        existente.ativo = True
        existente.ultimo_uso = datetime.utcnow()
    else:
        db.session.add(EnderecoCliente(cliente=cliente, endereco=endereco, bairro=bairro, complemento=request.form.get("complemento", "").strip() or None))
    db.session.commit()
    return redirect(url_for("farmacia.clientes"))


@farmacia_bp.post("/clientes/<int:cliente_id>/enderecos/<int:endereco_id>/desativar")
@role_required("farmacia")
def desativar_endereco(cliente_id: int, endereco_id: int):
    farmacia = _farmacia_logada()
    endereco = EnderecoCliente.query.join(Cliente).filter(
        EnderecoCliente.id == endereco_id, EnderecoCliente.cliente_id == cliente_id, Cliente.farmacia_id == farmacia.id
    ).first_or_404()
    endereco.ativo = False
    db.session.commit()
    return redirect(url_for("farmacia.clientes"))


@farmacia_bp.post("/clientes/<int:cliente_id>/enderecos/<int:endereco_id>/editar")
@role_required("farmacia")
def editar_endereco(cliente_id: int, endereco_id: int):
    farmacia = _farmacia_logada()
    endereco = EnderecoCliente.query.join(Cliente).filter(
        EnderecoCliente.id == endereco_id, EnderecoCliente.cliente_id == cliente_id, Cliente.farmacia_id == farmacia.id
    ).first_or_404()
    endereco.endereco = request.form.get("endereco", "").strip()
    endereco.bairro = request.form.get("bairro", "").strip()
    endereco.complemento = request.form.get("complemento", "").strip() or None
    if not endereco.endereco or not endereco.bairro:
        flash("Endereço e bairro são obrigatórios.", "error")
    else:
        db.session.commit()
    return redirect(url_for("farmacia.clientes"))


@farmacia_bp.get("/historico")
@role_required("farmacia")
def historico():
    farmacia = _farmacia_logada()
    page = request.args.get("page", 1, type=int)
    data_de = request.args.get("de", "")
    data_ate = request.args.get("ate", "")
    mostrar_canceladas = request.args.get("mostrar_canceladas") == "1"
    erro = None
    try:
        inicio, fim = parse_report_dates(data_de, data_ate)
        query = history_query(farmacia.id, inicio, fim, mostrar_canceladas)
        total_query = delivered_query(farmacia.id, inicio, fim)
        total = sum((entrega.valor_taxa for entrega in total_query.all()), Decimal("0.00"))
    except ValueError as error:
        query = Entrega.query.filter(False)
        total = Decimal("0.00")
        erro = str(error) if data_de or data_ate else None
    pagination = query.order_by(Entrega.data_criacao.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template(
        "farmacia/historico.html",
        farmacia=farmacia,
        pagination=pagination,
        total=total,
        data_de=data_de,
        data_ate=data_ate,
        mostrar_canceladas=mostrar_canceladas,
        erro=erro,
        brl=brl,
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


def criar_entrega(farmacia: Farmacia, form: EntregaForm, criada_por_central: bool = False) -> Entrega:
    bairro_preco = BairroPreco.query.filter_by(
        farmacia_id=farmacia.id, bairro=form.bairro_entrega.data
    ).first()
    if bairro_preco is None:
        raise ValueError("Bairro não cadastrado. Solicite à Central")
    cpf = normalize_cpf(form.cpf_cliente.data)
    telefone = normalize_phone(form.telefone_cliente.data)
    cliente = Cliente.query.filter_by(farmacia_id=farmacia.id, cpf=cpf).first()
    if cliente is None:
        cliente = Cliente(farmacia_id=farmacia.id, cpf=cpf)
        db.session.add(cliente)
    cliente.nome = form.nome_cliente.data.strip()
    cliente.telefone = telefone
    endereco = form.endereco_entrega.data.strip()
    endereco_cliente = next(
        (item for item in cliente.enderecos if item.ativo and normalize_text(item.endereco) == normalize_text(endereco)
         and normalize_text(item.bairro) == normalize_text(bairro_preco.bairro)),
        None,
    )
    if endereco_cliente is None:
        db.session.add(EnderecoCliente(
            cliente=cliente, endereco=endereco, bairro=bairro_preco.bairro, ultimo_uso=datetime.utcnow()
        ))
    else:
        endereco_cliente.ultimo_uso = datetime.utcnow()
    valor_troco = Decimal(form.valor_troco.data) if form.valor_troco.data else None
    valor_cobrar = Decimal(form.valor_cobrar.data) if form.valor_cobrar.data else None
    entrega = Entrega(
        farmacia_id=farmacia.id,
        cliente=cliente,
        nome_cliente=form.nome_cliente.data.strip(),
        telefone_cliente=telefone,
        endereco_entrega=endereco,
        bairro_entrega=bairro_preco.bairro,
        valor_taxa=Decimal(bairro_preco.valor_taxa),
        precisa_troco=bool(form.precisa_troco.data),
        valor_troco=valor_troco,
        usa_maquininha=bool(form.usa_maquininha.data),
        forma_pagamento=form.forma_pagamento.data,
        valor_cobrar=valor_cobrar,
        criada_por_central=criada_por_central,
        observacoes=(form.observacoes.data or "").strip() or None,
    )
    db.session.add(entrega)
    db.session.commit()
    from app.push import notificar_motoboys
    notificar_motoboys(entrega)
    return entrega


def _entregas_andamento(farmacia_id: int) -> list[Entrega]:
    return Entrega.query.filter(
        Entrega.farmacia_id == farmacia_id,
        Entrega.status.in_(("pendente", "aceita", "coletada")),
    ).order_by(Entrega.data_criacao.desc()).all()


def _telefone_normalizado(telefone: str) -> str:
    return normalize_phone(telefone)


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
