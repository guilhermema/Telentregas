from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.decorators import role_required
from app.extensions import db
from app.models import BairroPreco, Entrega, Farmacia, Motoboy, User
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

central_bp = Blueprint("central", __name__)
ATIVOS = ("pendente", "aceita", "coletada")


@central_bp.get("/")
@role_required("admin")
def dashboard():
    return render_template(
        "central/andamento.html",
        farmacias=Farmacia.query.order_by(Farmacia.razao_social).all(),
        status_filter=request.args.get("status", ""),
        farmacia_filter=request.args.get("farmacia_id", ""),
    )


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


@central_bp.post("/entregas/<int:entrega_id>/cancelar")
@role_required("admin")
def cancelar_entrega(entrega_id: int):
    motivo = request.form.get("motivo_cancelamento", "").strip()
    if len(motivo) < 3:
        flash("O motivo do cancelamento é obrigatório e deve ter pelo menos 3 caracteres.", "error")
        return redirect(url_for("central.dashboard"))
    result = db.session.execute(
        update(Entrega)
        .where(Entrega.id == entrega_id, Entrega.status.in_(ATIVOS))
        .values(status="cancelada", motivo_cancelamento=motivo, data_cancelamento=datetime.utcnow())
    )
    db.session.commit()
    if result.rowcount != 1:
        flash("A entrega já foi atualizada e não pode mais ser cancelada.", "error")
    else:
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
    return render_template("central/farmacias.html", farmacias=query.order_by(Farmacia.razao_social).all(), busca=busca)


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
        "username", "password", "razao_social", "cnpj_cpf", "endereco_fixo", "telefone", "responsavel_financeiro"
    )}
    if not _validar_credenciais(campos):
        return
    try:
        user = User(username=campos["username"], role="farmacia", ativo=True)
        user.set_password(campos["password"])
        farmacia = Farmacia(user=user, **{chave: campos[chave] for chave in (
            "razao_social", "cnpj_cpf", "endereco_fixo", "telefone", "responsavel_financeiro"
        )})
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
    for campo in ("razao_social", "cnpj_cpf", "endereco_fixo", "telefone", "responsavel_financeiro"):
        setattr(farmacia, campo, request.form.get(campo, "").strip())
    db.session.commit()
    flash("Farmácia atualizada.", "success")


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
    }
