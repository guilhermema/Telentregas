from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import json
import re
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import case, func, or_, update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.decorators import role_required
from app.extensions import db
from app.forms import EntregaForm
from app.models import BairroPreco, Cliente, Entrega, Farmacia, Motoboy, User
from app.blueprints.farmacia import _bairros_da_farmacia, _formulario, criar_entrega
from app.report import (
    brl,
    cancelled_data,
    delivered_query,
    history_query,
    parse_report_dates,
    period_bounds,
    report_data,
    safe_filename,
    subtotal_data,
    summary_data,
)
from app.report import SAO_PAULO
from app.utils.validators import mask_cpf, normalize_cpf

central_bp = Blueprint("central", __name__)
ATIVOS = ("pendente", "aceita", "coletada")
MUNICIPIOS_PATH = Path(__file__).resolve().parents[1] / "static" / "data" / "municipios.json"


def _municipios_ibge() -> dict:
    try:
        return json.loads(MUNICIPIOS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"estados": [], "municipios": {}}


def _localidade_valida(cidade: str, uf: str) -> bool:
    dados = _municipios_ibge()
    estados = {estado["sigla"] for estado in dados["estados"]}
    return uf in estados and cidade in dados["municipios"].get(uf, [])


def _geocodificar_farmacia(farmacia: Farmacia) -> None:
    consulta = f"{farmacia.endereco_fixo}, {farmacia.cidade}, {farmacia.uf}, Brasil"
    parametros = urlencode({"q": consulta, "format": "jsonv2", "limit": 1})
    try:
        requisicao = Request(
            f"https://nominatim.openstreetmap.org/search?{parametros}",
            headers={"User-Agent": "TelEntregas/1.0 contato-central"},
        )
        with urlopen(requisicao, timeout=5) as resposta:
            resultados = json.load(resposta)
        if resultados:
            farmacia.latitude = resultados[0].get("lat")
            farmacia.longitude = resultados[0].get("lon")
        else:
            farmacia.latitude = farmacia.longitude = None
            flash("Endereço não localizado. Ajuste o pino no mapa.", "error")
    except (OSError, ValueError, TypeError) as error:
        current_app.logger.warning("Falha ao geocodificar farmacia_id=%s: %s", farmacia.id, error)
        flash("Não foi possível localizar o endereço automaticamente. Ajuste o pino no mapa.", "error")


@central_bp.get("/")
@role_required("admin")
def dashboard():
    return render_template(
        "central/andamento.html",
        farmacias=Farmacia.query.order_by(Farmacia.razao_social).all(),
        status_filter=request.args.get("status", ""),
        farmacia_filter=request.args.get("farmacia_id", ""),
    )


@central_bp.route("/entregas/nova", methods=["GET", "POST"])
@role_required("admin")
def nova_entrega():
    farmacias = Farmacia.query.join(User).filter(User.ativo.is_(True)).order_by(Farmacia.razao_social).all()
    farmacia_id = request.form.get("farmacia_id", type=int) if request.method == "POST" else request.args.get("farmacia_id", type=int)
    farmacia = db.session.get(Farmacia, farmacia_id) if farmacia_id else None
    if farmacia is not None and farmacia not in farmacias:
        farmacia = None
    bairros = _bairros_da_farmacia(farmacia.id) if farmacia else []
    form = _formulario(bairros)
    if request.method == "POST" and farmacia is None:
        flash("Selecione uma farmácia.", "error")
    elif request.method == "POST" and form.validate_on_submit():
        try:
            criar_entrega(farmacia, form, criada_por_central=True)
        except ValueError as error:
            flash(str(error), "error")
        else:
            flash("Entrega criada pela Central.", "success")
            return redirect(url_for("central.dashboard"))
    return render_template(
        "farmacia/dashboard.html",
        farmacia=farmacia,
        form=form,
        bairros=bairros,
        taxas={bairro.bairro: f"R$ {bairro.valor_taxa:.2f}" for bairro in bairros},
        central_form=True,
        farmacias=farmacias,
        selected_farmacia_id=farmacia_id,
        cliente_lookup_url=url_for("central.buscar_cliente", farmacia_id=farmacia.id) if farmacia else "",
    )


@central_bp.get("/api/clientes/buscar/<int:farmacia_id>")
@role_required("admin")
def buscar_cliente(farmacia_id: int):
    farmacia = Farmacia.query.get_or_404(farmacia_id)
    try:
        cpf = normalize_cpf(request.args.get("cpf", ""))
    except ValueError:
        return jsonify({"encontrado": False}), 400
    cliente = Cliente.query.filter_by(farmacia_id=farmacia.id, cpf=cpf).first()
    if cliente is None:
        return jsonify({"encontrado": False, "mensagem": "Cliente novo"})
    enderecos = sorted((item for item in cliente.enderecos if item.ativo), key=lambda item: item.ultimo_uso, reverse=True)
    return jsonify({
        "encontrado": True, "cpf": mask_cpf(cliente.cpf), "nome": cliente.nome, "telefone": cliente.telefone,
        "enderecos": [{"id": item.id, "endereco": item.endereco, "bairro": item.bairro, "complemento": item.complemento} for item in enderecos],
    })


def _dashboard_payload():
    agora = datetime.utcnow()
    hoje = datetime.now(SAO_PAULO).date()
    inicio_hoje, _ = period_bounds(hoje, hoje)
    primeiro_mes, _ = period_bounds(hoje.replace(day=1), hoje)
    inicio_graficos, fim_graficos = period_bounds(hoje - timedelta(days=29), hoje)
    limite_pendente = agora - timedelta(minutes=current_app.config["PENDENTE_ALERTA_MIN"])
    limite_aceita = agora - timedelta(minutes=current_app.config["ACEITA_ALERTA_MIN"])
    limite_coletada = agora - timedelta(minutes=current_app.config["COLETADA_ALERTA_MIN"])

    agregados = db.session.query(
        Entrega.status,
        func.count(Entrega.id),
        func.coalesce(func.sum(Entrega.valor_taxa), 0),
    ).filter(
        Entrega.data_criacao >= inicio_hoje,
        Entrega.data_criacao <= agora,
    ).group_by(Entrega.status).all()
    por_status = {status: (int(quantidade), Decimal(total or 0)) for status, quantidade, total in agregados}
    cards = {
        "criadas": sum(valor[0] for valor in por_status.values()),
        "entregues": por_status.get("entregue", (0, Decimal("0.00")))[0],
        "em_rota": sum(por_status.get(status, (0, Decimal("0.00")))[0] for status in ("aceita", "coletada")),
        "pendentes_sem_motoboy": db.session.query(func.count(Entrega.id)).filter(
            Entrega.data_criacao >= inicio_hoje, Entrega.data_criacao <= agora,
            Entrega.status == "pendente", Entrega.motoboy_id.is_(None),
        ).scalar() or 0,
        "canceladas": por_status.get("cancelada", (0, Decimal("0.00")))[0],
        "taxas_entregues": f"{por_status.get('entregue', (0, Decimal('0.00')))[1]:.2f}",
    }

    if db.engine.dialect.name == "postgresql":
        data_local = func.date(
            func.timezone(
                "America/Sao_Paulo",
                func.timezone("UTC", Entrega.data_entrega),
            )
        )
        hora_local = func.cast(
            func.to_char(
                func.timezone(
                    "America/Sao_Paulo",
                    func.timezone("UTC", Entrega.data_entrega),
                ),
                "HH24",
            ),
            db.Integer,
        )
    else:
        # SQLite is used by the lightweight test scripts and has no named
        # timezone conversion; the application timezone is UTC-3.
        data_local = func.date(func.datetime(Entrega.data_entrega, "-3 hours"))
        hora_local = func.cast(
            func.strftime("%H", func.datetime(Entrega.data_entrega, "-3 hours")),
            db.Integer,
        )

    dias_agregados = db.session.query(
        data_local.label("dia"), func.count(Entrega.id)
    ).filter(
        Entrega.status == "entregue",
        Entrega.data_entrega >= inicio_graficos,
        Entrega.data_entrega < fim_graficos,
    ).group_by(data_local).all()
    dias_por_data = {str(dia): int(total) for dia, total in dias_agregados}
    entregas_por_dia = [
        {
            "data": (hoje - timedelta(days=indice)).isoformat(),
            "quantidade": dias_por_data.get((hoje - timedelta(days=indice)).isoformat(), 0),
        }
        for indice in range(13, -1, -1)
    ]

    horas_agregadas = db.session.query(
        hora_local.label("hora"), func.count(Entrega.id)
    ).filter(
        Entrega.status == "entregue",
        Entrega.data_entrega >= inicio_graficos,
        Entrega.data_entrega < fim_graficos,
    ).group_by(hora_local).all()
    horas_por_hora = {int(hora): int(total) for hora, total in horas_agregadas if hora is not None}
    entregas_por_hora = [
        {"hora": hora, "quantidade": horas_por_hora.get(hora, 0)}
        for hora in range(24)
    ]

    def alertas_entregas(status, limite, timestamp):
        return Entrega.query.filter(
            Entrega.status == status, timestamp < limite
        ).order_by(timestamp.asc()).all()

    alertas = []
    for titulo, status, limite, timestamp in (
        ("Pendente há muito tempo", "pendente", limite_pendente, Entrega.data_criacao),
        ("Aceita aguardando coleta", "aceita", limite_aceita, Entrega.data_aceite),
        ("Coletada aguardando entrega", "coletada", limite_coletada, Entrega.data_coleta),
    ):
        for entrega in alertas_entregas(status, limite, timestamp):
            alertas.append({
                "tipo": "entrega",
                "titulo": titulo,
                "texto": f"{entrega.farmacia.razao_social} · {entrega.nome_cliente} · {entrega.bairro_entrega}",
                "url": url_for("central.dashboard", farmacia_id=entrega.farmacia_id, status=status),
                "entrega_id": entrega.id,
            })

    from app.models import PushSubscription
    motoboys_sem_push = Motoboy.query.join(User).filter(
        User.ativo.is_(True),
        ~db.session.query(PushSubscription.id).filter(PushSubscription.user_id == Motoboy.user_id).exists(),
    ).all()
    for motoboy in motoboys_sem_push:
        alertas.append({
            "tipo": "motoboy",
            "titulo": "Motoboy sem notificações push",
            "texto": motoboy.nome,
            "url": url_for("central.motoboys"),
        })
    farmacias_sem_bairro = Farmacia.query.join(User).outerjoin(BairroPreco).filter(
        User.ativo.is_(True)
    ).group_by(Farmacia.id).having(func.count(BairroPreco.id) == 0).all()
    for farmacia in farmacias_sem_bairro:
        alertas.append({
            "tipo": "farmacia",
            "titulo": "Farmácia sem tabela de preços",
            "texto": farmacia.razao_social,
            "url": url_for("central.precos", farmacia_id=farmacia.id),
        })

    ativos = Entrega.query.filter(Entrega.status.in_(ATIVOS)).all()
    ids_alerta = {item["entrega_id"] for item in alertas if "entrega_id" in item}
    entregas_json = []
    farmacia_filter = request.args.get("farmacia_id", type=int)
    status_filter = request.args.get("status")
    for entrega in ativos:
        if farmacia_filter and entrega.farmacia_id != farmacia_filter:
            continue
        if status_filter in ATIVOS and entrega.status != status_filter:
            continue
        item = _entrega_json(entrega)
        item["alerta"] = entrega.id in ids_alerta
        entregas_json.append(item)

    motoboys = []
    for motoboy in Motoboy.query.join(User).filter(User.ativo.is_(True)).order_by(Motoboy.nome).all():
        corridas = [entrega for entrega in ativos if entrega.motoboy_id == motoboy.id]
        atividades = [
            data for entrega in corridas
            for data in (entrega.data_aceite, entrega.data_coleta, entrega.data_entrega)
            if data is not None
        ]
        ultima = max(atividades) if atividades else None
        push_ativo = db.session.query(PushSubscription.id).filter(
            PushSubscription.user_id == motoboy.user_id
        ).first() is not None
        motoboys.append({
            "id": motoboy.id,
            "nome": motoboy.nome,
            "corridas": len(corridas),
            "ultima_atividade": ultima.isoformat() if ultima else None,
            "push_ativo": push_ativo,
        })

    resumo = db.session.query(
        Farmacia.id, Farmacia.razao_social,
        func.sum(case((Entrega.data_criacao >= inicio_hoje, 1), else_=0)),
        func.count(Entrega.id),
        func.coalesce(func.sum(case((Entrega.status == "entregue", Entrega.valor_taxa), else_=0)), 0),
    ).outerjoin(Entrega, (Entrega.farmacia_id == Farmacia.id) & (Entrega.data_criacao >= primeiro_mes) & (Entrega.data_criacao <= agora)).group_by(
        Farmacia.id, Farmacia.razao_social
    ).order_by(Farmacia.razao_social).all()
    farmacias_resumo = [{
        "id": farmacia_id, "nome": nome, "hoje": int(hoje_count or 0),
        "mes": int(mes_count or 0), "valor_mes": f"{Decimal(valor or 0):.2f}",
        "url": url_for("central.cliente_detalhe", farmacia_id=farmacia_id),
    } for farmacia_id, nome, hoje_count, mes_count, valor in resumo]
    return {
        "cards": cards, "alertas": alertas, "motoboys": motoboys,
        "entregas": entregas_json, "farmacias": farmacias_resumo,
        "graficos": {
            "entregas_por_dia": entregas_por_dia,
            "entregas_por_hora": entregas_por_hora,
        },
    }


@central_bp.get("/api/dashboard")
@role_required("admin")
def dashboard_json():
    return jsonify(_dashboard_payload())


@central_bp.get("/api/andamento")
@role_required("admin")
def andamento_json():
    query = Entrega.query.filter(Entrega.status.in_(ATIVOS))
    farmacia_id = request.args.get("farmacia_id", type=int)
    status = request.args.get("status")
    if farmacia_id:
        query = query.filter(Entrega.farmacia_id == farmacia_id)
    if status in ATIVOS:
        query = query.filter(Entrega.status == status)
    entregas = query.order_by(Entrega.data_criacao.desc()).all()
    return jsonify({"entregas": [_entrega_json(entrega) for entrega in entregas]})


@central_bp.post("/entregas/<int:entrega_id>/devolver")
@role_required("admin")
def devolver_a_praca(entrega_id: int):
    motivo = request.form.get("motivo_devolucao", "").strip()
    if len(motivo) < 3:
        flash("O motivo da devolução é obrigatório e deve ter pelo menos 3 caracteres.", "error")
        return redirect(url_for("central.dashboard"))
    entrega = Entrega.query.filter_by(id=entrega_id).first()
    if entrega is None:
        flash("Entrega não encontrada.", "error")
        return redirect(url_for("central.dashboard"))
    motoboy_id = entrega.motoboy_id
    result = db.session.execute(
        update(Entrega).where(
            Entrega.id == entrega_id, Entrega.status == "aceita"
        ).values(
            status="pendente", motoboy_id=None, data_aceite=None,
            motivo_devolucao=motivo, devolvida_em=datetime.utcnow(),
            devolvida_por_user_id=current_user.id,
            motoboy_anterior_id=motoboy_id,
        )
    )
    db.session.commit()
    if result.rowcount != 1:
        flash("A entrega já mudou de status e não foi devolvida à praça.", "error")
    else:
        from app.push import notificar_motoboys
        notificar_motoboys(entrega)
        flash("Entrega devolvida à praça.", "success")
    return redirect(url_for("central.dashboard"))


@central_bp.post("/entregas/<int:entrega_id>/cancelar")
@role_required("admin")
def cancelar_entrega(entrega_id: int):
    motivo = request.form.get("motivo_cancelamento", "").strip()
    if len(motivo) < 3:
        flash("O motivo do cancelamento é obrigatório e deve ter pelo menos 3 caracteres.", "error")
        return redirect(url_for("central.dashboard"))
    entrega = Entrega.query.filter_by(id=entrega_id).first()
    motoboy_id = entrega.motoboy_id if entrega else None
    result = db.session.execute(
        update(Entrega)
        .where(Entrega.id == entrega_id, Entrega.status.in_(ATIVOS))
        .values(status="cancelada", motivo_cancelamento=motivo, data_cancelamento=datetime.utcnow())
    )
    db.session.commit()
    if result.rowcount != 1:
        flash("A entrega já foi atualizada e não pode mais ser cancelada.", "error")
    else:
        if motoboy_id:
            from app.push import notificar_cancelamento

            notificar_cancelamento(entrega, motoboy_id)
        flash("Entrega cancelada.", "success")
    return redirect(url_for("central.dashboard"))


@central_bp.route("/farmacias", methods=["GET", "POST"])
@role_required("admin")
def farmacias():
    if request.method == "POST":
        _criar_farmacia()
    busca = request.args.get("busca", "").strip()
    query = Farmacia.query.join(User)
    if busca:
        termo = f"%{busca}%"
        query = query.filter((Farmacia.razao_social.ilike(termo)) | (User.username.ilike(termo)))
    return render_template(
        "central/farmacias.html",
        farmacias=query.order_by(Farmacia.razao_social).all(),
        busca=busca,
        municipios_data=_municipios_ibge(),
    )


@central_bp.post("/farmacias/<int:farmacia_id>/editar")
@role_required("admin")
def editar_farmacia(farmacia_id: int):
    farmacia = Farmacia.query.get_or_404(farmacia_id)
    _atualizar_farmacia(farmacia)
    return redirect(url_for("central.farmacias"))


@central_bp.post("/farmacias/<int:farmacia_id>/senha")
@role_required("admin")
def resetar_senha_farmacia(farmacia_id: int):
    farmacia = Farmacia.query.get_or_404(farmacia_id)
    _resetar_senha(farmacia.user)
    return redirect(url_for("central.farmacias"))


@central_bp.post("/farmacias/<int:farmacia_id>/status")
@role_required("admin")
def status_farmacia(farmacia_id: int):
    farmacia = Farmacia.query.get_or_404(farmacia_id)
    farmacia.user.ativo = not farmacia.user.ativo
    db.session.commit()
    flash("Status da farmácia atualizado.", "success")
    return redirect(url_for("central.farmacias"))


@central_bp.route("/motoboys", methods=["GET", "POST"])
@role_required("admin")
def motoboys():
    if request.method == "POST":
        _criar_motoboy()
    busca = request.args.get("busca", "").strip()
    query = Motoboy.query.join(User)
    if busca:
        termo = f"%{busca}%"
        query = query.filter((Motoboy.nome.ilike(termo)) | (User.username.ilike(termo)))
    return render_template("central/motoboys.html", motoboys=query.order_by(Motoboy.nome).all(), busca=busca)


@central_bp.post("/motoboys/<int:motoboy_id>/editar")
@role_required("admin")
def editar_motoboy(motoboy_id: int):
    motoboy = Motoboy.query.get_or_404(motoboy_id)
    motoboy.nome = request.form.get("nome", "").strip()
    motoboy.telefone = request.form.get("telefone", "").strip()
    motoboy.placa_moto = request.form.get("placa_moto", "").strip()
    db.session.commit()
    flash("Motoboy atualizado.", "success")
    return redirect(url_for("central.motoboys"))


@central_bp.post("/motoboys/<int:motoboy_id>/senha")
@role_required("admin")
def resetar_senha_motoboy(motoboy_id: int):
    motoboy = Motoboy.query.get_or_404(motoboy_id)
    _resetar_senha(motoboy.user)
    return redirect(url_for("central.motoboys"))


@central_bp.post("/motoboys/<int:motoboy_id>/status")
@role_required("admin")
def status_motoboy(motoboy_id: int):
    motoboy = Motoboy.query.get_or_404(motoboy_id)
    motoboy.user.ativo = not motoboy.user.ativo
    db.session.commit()
    flash("Status do motoboy atualizado.", "success")
    return redirect(url_for("central.motoboys"))


@central_bp.route("/precos", methods=["GET", "POST"])
@role_required("admin")
def precos():
    farmacias = Farmacia.query.order_by(Farmacia.razao_social).all()
    farmacia_id = request.values.get("farmacia_id", type=int)
    farmacia = Farmacia.query.get(farmacia_id) if farmacia_id else (farmacias[0] if farmacias else None)
    if request.method == "POST" and farmacia:
        _salvar_preco(farmacia)
    bairros = BairroPreco.query.filter_by(farmacia_id=farmacia.id).order_by(BairroPreco.bairro).all() if farmacia else []
    return render_template("central/precos.html", farmacias=farmacias, farmacia=farmacia, bairros=bairros)


@central_bp.post("/precos/<int:bairro_id>/editar")
@role_required("admin")
def editar_preco(bairro_id: int):
    bairro = BairroPreco.query.get_or_404(bairro_id)
    _dados_preco(bairro)
    return redirect(url_for("central.precos", farmacia_id=bairro.farmacia_id))


@central_bp.post("/precos/<int:bairro_id>/excluir")
@role_required("admin")
def excluir_preco(bairro_id: int):
    bairro = BairroPreco.query.get_or_404(bairro_id)
    farmacia_id = bairro.farmacia_id
    db.session.delete(bairro)
    db.session.commit()
    flash("Bairro excluído da tabela de preços.", "success")
    return redirect(url_for("central.precos", farmacia_id=farmacia_id))


@central_bp.get("/clientes")
@role_required("admin")
def clientes():
    busca = request.args.get("busca", "").strip()
    query = Farmacia.query
    if busca:
        query = query.filter(Farmacia.razao_social.ilike(f"%{busca}%"))
    inicio = datetime.combine(datetime.utcnow().date().replace(day=1), time.min)
    farmacias = query.order_by(Farmacia.razao_social).all()
    totais = {
        farmacia.id: Entrega.query.filter(
            Entrega.farmacia_id == farmacia.id,
            Entrega.data_criacao >= inicio,
        ).count()
        for farmacia in farmacias
    }
    return render_template("central/clientes.html", farmacias=farmacias, totais=totais, busca=busca)


@central_bp.get("/clientes/<int:farmacia_id>")
@role_required("admin")
def cliente_detalhe(farmacia_id: int):
    farmacia = Farmacia.query.get_or_404(farmacia_id)
    clientes_farmacia = Cliente.query.filter_by(farmacia_id=farmacia.id).order_by(Cliente.nome).all()
    data_de = request.args.get("de", "")
    data_ate = request.args.get("ate", "")
    try:
        inicio, fim = parse_report_dates(data_de, data_ate)
        query = history_query(farmacia.id, inicio, fim, request.args.get("mostrar_canceladas") == "1")
        total_query = delivered_query(farmacia.id, inicio, fim)
        total = sum((entrega.valor_taxa for entrega in total_query.all()), Decimal("0.00"))
        erro = None
    except ValueError as error:
        query = Entrega.query.filter(False)
        total = Decimal("0.00")
        erro = str(error) if data_de or data_ate else None
    pagination = query.order_by(Entrega.data_criacao.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=20, error_out=False
    )
    return render_template(
        "central/cliente_detalhe.html",
        farmacia=farmacia,
        pagination=pagination,
        total=total,
        data_de=data_de,
        data_ate=data_ate,
        mostrar_canceladas=request.args.get("mostrar_canceladas") == "1",
        erro=erro,
        brl=brl,
        clientes_farmacia=clientes_farmacia,
        mask_cpf=mask_cpf,
    )


@central_bp.get("/clientes/<int:farmacia_id>/relatorio.pdf")
@role_required("admin")
def relatorio_pdf(farmacia_id: int):
    farmacia = Farmacia.query.get_or_404(farmacia_id)
    try:
        inicio, fim = parse_report_dates(request.args.get("de"), request.args.get("ate"))
    except ValueError as error:
        abort(400, description=str(error))
    entregas = delivered_query(farmacia.id, inicio, fim).order_by(Entrega.data_entrega.asc()).all()
    _, fim_utc = period_bounds(inicio, fim)
    inicio_utc, _ = period_bounds(inicio, fim)
    canceladas = Entrega.query.filter(
        Entrega.farmacia_id == farmacia.id,
        Entrega.status == "cancelada",
        Entrega.data_cancelamento.is_not(None),
        Entrega.data_cancelamento >= inicio_utc,
        Entrega.data_cancelamento < fim_utc,
    ).order_by(Entrega.data_cancelamento.asc()).all()
    rows, total = report_data(entregas)
    try:
        from flask import make_response
        from weasyprint import HTML
        from flask import render_template

        html = render_template(
            "central/relatorio.html",
            farmacia=farmacia,
            inicio=inicio,
            fim=fim,
            emitido=datetime.now(SAO_PAULO),
            rows=rows,
            subtotais=subtotal_data(entregas),
            total=total,
            brl=brl,
            resumo=summary_data(entregas, canceladas),
            canceladas=cancelled_data(canceladas),
            detalhado=request.args.get("detalhado") == "1",
        )
        response = make_response(HTML(string=html).write_pdf())
    except ImportError as error:
        abort(500, description="WeasyPrint não está instalado. Instale as dependências do requirements.txt.")
    except OSError as error:
        abort(500, description="As bibliotecas do sistema do WeasyPrint não estão instaladas.")
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=relatorio_{safe_filename(farmacia.razao_social)}_"
        f"{inicio.isoformat()}_{fim.isoformat()}.pdf"
    )
    return response


def _criar_farmacia():
    campos = {nome: request.form.get(nome, "").strip() for nome in (
        "username", "password", "razao_social", "cnpj_cpf", "endereco_fixo", "cidade", "uf", "telefone", "responsavel_financeiro"
    )}
    if not _validar_credenciais(campos):
        return
    campos["uf"] = campos["uf"].upper()
    if not _localidade_valida(campos["cidade"], campos["uf"]):
        flash("Selecione um município válido para a UF informada.", "error")
        return
    try:
        user = User(username=campos["username"], role="farmacia", ativo=True)
        user.set_password(campos["password"])
        farmacia = Farmacia(user=user, **{chave: campos[chave] for chave in (
            "razao_social", "cnpj_cpf", "endereco_fixo", "cidade", "uf", "telefone", "responsavel_financeiro"
        )})
        _geocodificar_farmacia(farmacia)
        db.session.add_all([user, farmacia])
        db.session.commit()
        flash("Farmácia criada com sucesso.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Este username já está cadastrado.", "error")


def _criar_motoboy():
    campos = {nome: request.form.get(nome, "").strip() for nome in ("username", "password", "nome", "telefone", "placa_moto")}
    if not _validar_credenciais(campos):
        return
    try:
        user = User(username=campos["username"], role="motoboy", ativo=True)
        user.set_password(campos["password"])
        motoboy = Motoboy(user=user, nome=campos["nome"], telefone=campos["telefone"], placa_moto=campos["placa_moto"])
        db.session.add_all([user, motoboy])
        db.session.commit()
        flash("Motoboy criado com sucesso.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Este username já está cadastrado.", "error")


def _validar_credenciais(campos: dict) -> bool:
    if not campos["username"] or not campos["password"]:
        flash("Username e senha inicial são obrigatórios.", "error")
        return False
    if len(campos["password"]) < 8:
        flash("A senha deve ter pelo menos 8 caracteres.", "error")
        return False
    if User.query.filter_by(username=campos["username"]).first():
        flash("Este username já está cadastrado.", "error")
        return False
    return True


def _atualizar_farmacia(farmacia: Farmacia):
    dados = {
        campo: request.form.get(campo, "").strip()
        for campo in ("razao_social", "cnpj_cpf", "endereco_fixo", "cidade", "uf", "telefone", "responsavel_financeiro")
    }
    dados["uf"] = dados["uf"].upper()
    if not _localidade_valida(dados["cidade"], dados["uf"]):
        flash("Selecione um município válido para a UF informada.", "error")
        return
    for campo, valor in dados.items():
        setattr(farmacia, campo, valor)
    _geocodificar_farmacia(farmacia)
    db.session.commit()
    flash("Farmácia atualizada.", "success")


@central_bp.post("/farmacias/<int:farmacia_id>/posicao")
@role_required("admin")
def salvar_posicao_farmacia(farmacia_id: int):
    farmacia = Farmacia.query.get_or_404(farmacia_id)
    try:
        latitude = Decimal(request.form.get("latitude", ""))
        longitude = Decimal(request.form.get("longitude", ""))
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        flash("Informe uma posição válida no mapa.", "error")
        return redirect(url_for("central.farmacias"))
    farmacia.latitude = latitude
    farmacia.longitude = longitude
    db.session.commit()
    flash("Posição da farmácia salva.", "success")
    return redirect(url_for("central.farmacias"))


def _resetar_senha(user: User):
    senha = request.form.get("password", "")
    if len(senha) < 8:
        flash("A nova senha deve ter pelo menos 8 caracteres.", "error")
        return
    user.password_hash = generate_password_hash(senha)
    db.session.commit()
    flash("Senha redefinida com sucesso.", "success")


def _salvar_preco(farmacia: Farmacia):
    bairro = BairroPreco(farmacia_id=farmacia.id)
    _dados_preco(bairro)


def _dados_preco(bairro: BairroPreco):
    nome = _normalizar_bairro(request.form.get("bairro", ""))
    valor = _decimal(request.form.get("valor_taxa", ""))
    if not nome or valor is None or valor < 0:
        flash("Informe um bairro e um valor válido.", "error")
        return
    existente = BairroPreco.query.filter_by(farmacia_id=bairro.farmacia_id).all()
    chave = _chave_bairro(nome)
    if any(item.id != bairro.id and _chave_bairro(item.bairro) == chave for item in existente):
        flash("Este bairro já existe para esta farmácia.", "error")
        return
    bairro.bairro = nome
    bairro.valor_taxa = valor
    db.session.add(bairro)
    try:
        db.session.commit()
        flash("Tabela de preços atualizada.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Este bairro já existe para esta farmácia.", "error")


def _decimal(value: str):
    try:
        return Decimal(value.replace(".", "").replace(",", ".")) if "," in value else Decimal(value)
    except (InvalidOperation, AttributeError):
        return None


def _normalizar_bairro(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _chave_bairro(value: str) -> str:
    sem_acentos = unicodedata.normalize("NFKD", value)
    return "".join(char for char in sem_acentos if not unicodedata.combining(char)).casefold()


def _parse_date(value: str | None):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None
    except ValueError:
        return None


def _filtrar_periodo(query, data_de, data_ate):
    if data_de:
        query = query.filter(Entrega.data_criacao >= datetime.combine(data_de, time.min))
    if data_ate:
        query = query.filter(Entrega.data_criacao < datetime.combine(data_ate + timedelta(days=1), time.min))
    return query


def _entrega_json(entrega: Entrega) -> dict:
    agora = datetime.utcnow()
    status_data = {
        "pendente": entrega.data_criacao,
        "aceita": entrega.data_aceite,
        "coletada": entrega.data_coleta,
    }.get(entrega.status)
    minutos_criacao = max(0, int((agora - entrega.data_criacao).total_seconds() // 60))
    minutos_status = max(0, int((agora - status_data).total_seconds() // 60)) if status_data else 0
    limites = {
        "pendente": current_app.config["PENDENTE_ALERTA_MIN"],
        "aceita": current_app.config["ACEITA_ALERTA_MIN"],
        "coletada": current_app.config["COLETADA_ALERTA_MIN"],
    }
    return {
        "id": entrega.id,
        "farmacia": entrega.farmacia.razao_social,
        "cliente": entrega.nome_cliente,
        "bairro": entrega.bairro_entrega,
        "taxa": f"{entrega.valor_taxa:.2f}",
        "status": entrega.status,
        "motoboy": entrega.motoboy.nome if entrega.motoboy else None,
        "criacao": entrega.data_criacao.isoformat(),
        "aceite": entrega.data_aceite.isoformat() if entrega.data_aceite else None,
        "coleta": entrega.data_coleta.isoformat() if entrega.data_coleta else None,
        "minutos_criacao": minutos_criacao,
        "minutos_status": minutos_status,
        "limite_status": limites.get(entrega.status),
        "criada_por_central": entrega.criada_por_central,
    }
