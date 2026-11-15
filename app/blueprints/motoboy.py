from datetime import datetime
from urllib.parse import quote

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import case, update

from app.extensions import db
from app.models import Entrega, Motoboy, PushSubscription
from app.push import vapid_public_key

from app.decorators import role_required

motoboy_bp = Blueprint("motoboy", __name__)


@motoboy_bp.get("/")
@role_required("motoboy")
def dashboard():
    motoboy = _motoboy_logado()
    return render_template(
        "motoboy/dashboard.html",
        motoboy=motoboy,
        vapid_public_key=vapid_public_key(),
    )


@motoboy_bp.get("/api/praca")
@role_required("motoboy")
def praca_json():
    Entrega.query.session.expire_all()
    motoboy = _motoboy_logado()
    entregas = Entrega.query.filter_by(status="pendente").order_by(Entrega.data_criacao.asc()).all()
    ativas = Entrega.query.filter(
        Entrega.motoboy_id == motoboy.id,
        Entrega.status.in_(("aceita", "coletada")),
    ).order_by(
        case((Entrega.status == "coletada", 0), else_=1),
        Entrega.data_aceite.asc(),
    ).all()
    canceladas = Entrega.query.filter_by(motoboy_id=motoboy.id, status="cancelada").order_by(
        Entrega.data_cancelamento.desc()
    ).limit(30).all()
    devolvidas = Entrega.query.filter(
        Entrega.motoboy_anterior_id == motoboy.id,
        Entrega.status == "pendente",
    ).order_by(Entrega.devolvida_em.desc()).limit(30).all()
    return jsonify({
        "entregas": [_praca_json(entrega) for entrega in entregas],
        "ativas": [_ativa_json(entrega) for entrega in ativas],
        "canceladas": [_cancelada_json(entrega) for entrega in canceladas],
        "devolvidas": [_devolvida_json(entrega) for entrega in devolvidas],
    })


@motoboy_bp.post("/entregas/<int:entrega_id>/aceitar")
@role_required("motoboy")
def aceitar(entrega_id: int):
    motoboy = _motoboy_logado()
    result = db.session.execute(
        update(Entrega)
        .where(Entrega.id == entrega_id, Entrega.status == "pendente")
        .values(motoboy_id=motoboy.id, status="aceita", data_aceite=datetime.utcnow())
    )
    db.session.commit()
    if result.rowcount != 1:
        return _acao_response(False, "Esta corrida já foi aceita por outro motoboy", 409)
    return _acao_response(True, "Corrida aceita.")


@motoboy_bp.post("/entregas/<int:entrega_id>/avancar")
@role_required("motoboy")
def avancar(entrega_id: int):
    motoboy = _motoboy_logado()
    entrega = Entrega.query.filter_by(id=entrega_id, motoboy_id=motoboy.id).first_or_404()
    proximo = {"aceita": ("coletada", "data_coleta"), "coletada": ("entregue", "data_entrega")}
    destino = proximo.get(entrega.status)
    if destino is None:
        return _acao_response(False, "Esta corrida não pode avançar a partir do status atual.", 409)

    status_novo, campo_data = destino
    result = db.session.execute(
        update(Entrega)
        .where(
            Entrega.id == entrega.id,
            Entrega.motoboy_id == motoboy.id,
            Entrega.status == entrega.status,
        )
        .values(status=status_novo, **{campo_data: datetime.utcnow()})
    )
    db.session.commit()
    if result.rowcount != 1:
        return _acao_response(False, "A corrida foi atualizada. Recarregue a lista.", 409)
    return _acao_response(True, f"Status atualizado para {status_novo}.")


@motoboy_bp.post("/entregas/coletar")
@role_required("motoboy")
def coletar_selecionadas():
    motoboy = _motoboy_logado()
    payload = request.get_json(silent=True)
    ids = payload.get("entrega_ids") if isinstance(payload, dict) else None
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "mensagem": "Selecione ao menos uma corrida."}), 400
    if len(ids) > 20:
        return jsonify({"ok": False, "mensagem": "Você pode coletar no máximo 20 corridas por vez."}), 400

    ids_convertidos = []
    for valor in ids:
        if isinstance(valor, bool):
            return jsonify({"ok": False, "mensagem": "Os identificadores das corridas são inválidos."}), 400
        if not isinstance(valor, (int, str)):
            return jsonify({"ok": False, "mensagem": "Os identificadores das corridas são inválidos."}), 400
        try:
            id_convertido = int(valor)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "mensagem": "Os identificadores das corridas são inválidos."}), 400
        if id_convertido <= 0 or (isinstance(valor, str) and str(id_convertido) != valor.strip()):
            return jsonify({"ok": False, "mensagem": "Os identificadores das corridas são inválidos."}), 400
        ids_convertidos.append(id_convertido)
    if len(set(ids_convertidos)) != len(ids_convertidos):
        return jsonify({"ok": False, "mensagem": "A mesma corrida foi selecionada mais de uma vez."}), 400

    agora = datetime.utcnow()
    coletadas = []
    falharam = []
    for entrega_id in ids_convertidos:
        result = db.session.execute(
            update(Entrega).where(
                Entrega.id == entrega_id,
                Entrega.motoboy_id == motoboy.id,
                Entrega.status == "aceita",
            ).values(status="coletada", data_coleta=agora)
        )
        if result.rowcount == 1:
            coletadas.append(entrega_id)
        else:
            falharam.append(entrega_id)
    db.session.commit()
    if falharam:
        mensagem = (
            f"{len(coletadas)} corrida(s) coletada(s). "
            f"Não foi possível coletar {len(falharam)} corrida(s), pois o status já havia mudado."
        )
    else:
        mensagem = f"{len(coletadas)} corrida(s) marcada(s) como coletada(s)."
    return jsonify({
        "ok": bool(coletadas),
        "mensagem": mensagem,
        "coletadas": coletadas,
        "falharam": falharam,
    })


@motoboy_bp.post("/api/push-subscription")
@role_required("motoboy")
def salvar_subscription():
    dados = request.get_json(silent=True) or {}
    endpoint = dados.get("endpoint")
    keys = dados.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return jsonify({"erro": "Subscription inválida."}), 400

    subscription = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if subscription is None:
        subscription = PushSubscription(
            user_id=current_user.id,
            endpoint=endpoint,
            p256dh=keys["p256dh"],
            auth=keys["auth"],
            user_agent=request.user_agent.string[:500],
        )
        db.session.add(subscription)
    else:
        subscription.user_id = current_user.id
        subscription.p256dh = keys["p256dh"]
        subscription.auth = keys["auth"]
        subscription.user_agent = request.user_agent.string[:500]
    db.session.commit()
    return jsonify({"ok": True})


def _motoboy_logado() -> Motoboy:
    motoboy = Motoboy.query.filter_by(user_id=current_user.id).first()
    if motoboy is None:
        abort(404)
    return motoboy


def _praca_json(entrega: Entrega) -> dict:
    farmacia = entrega.farmacia
    endereco = ", ".join(filter(None, (farmacia.endereco_fixo, farmacia.cidade, farmacia.uf)))
    return {
        "id": entrega.id,
        "bairro": entrega.bairro_entrega,
        "valor_taxa": f"{entrega.valor_taxa:.2f}",
        "precisa_troco": entrega.precisa_troco,
        "valor_troco": f"{entrega.valor_troco:.2f}" if entrega.valor_troco is not None else None,
        "usa_maquininha": entrega.usa_maquininha,
        "pagamento": _pagamento_texto(entrega),
        "farmacia": entrega.farmacia.razao_social,
        "farmacia_endereco": endereco,
        "farmacia_latitude": float(farmacia.latitude) if farmacia.latitude is not None else None,
        "farmacia_longitude": float(farmacia.longitude) if farmacia.longitude is not None else None,
    }


def _ativa_json(entrega: Entrega) -> dict:
    endereco_cliente = ", ".join(
        valor for valor in (
            entrega.endereco_entrega,
            entrega.bairro_entrega,
            entrega.farmacia.cidade,
            entrega.farmacia.uf,
        ) if valor
    )
    farmacia = entrega.farmacia
    endereco_farmacia = ", ".join(filter(None, (farmacia.endereco_fixo, farmacia.cidade, farmacia.uf)))
    destino_farmacia = (
        f"{farmacia.latitude},{farmacia.longitude}"
        if farmacia.latitude is not None and farmacia.longitude is not None
        else endereco_farmacia
    )
    destino_cliente = endereco_cliente
    destino_principal = destino_farmacia if entrega.status == "aceita" else destino_cliente
    principal = quote(destino_principal, safe="")
    farmacia_destino = quote(destino_farmacia, safe="")
    cliente_destino = quote(destino_cliente, safe="")
    return {
        "id": entrega.id,
        "status": entrega.status,
        "farmacia": entrega.farmacia.razao_social,
        "farmacia_endereco": endereco_farmacia,
        "farmacia_latitude": float(farmacia.latitude) if farmacia.latitude is not None else None,
        "farmacia_longitude": float(farmacia.longitude) if farmacia.longitude is not None else None,
        "nome_cliente": entrega.nome_cliente,
        "telefone_cliente": entrega.telefone_cliente,
        "endereco_entrega": entrega.endereco_entrega,
        "bairro": entrega.bairro_entrega,
        "valor_taxa": f"{entrega.valor_taxa:.2f}",
        "precisa_troco": entrega.precisa_troco,
        "valor_troco": f"{entrega.valor_troco:.2f}" if entrega.valor_troco is not None else None,
        "usa_maquininha": entrega.usa_maquininha,
        "pagamento": _pagamento_texto(entrega),
        "observacoes": entrega.observacoes,
        "data_aceite": entrega.data_aceite.isoformat() if entrega.data_aceite else None,
        "data_coleta": entrega.data_coleta.isoformat() if entrega.data_coleta else None,
        "endereco_completo": endereco_cliente,
        "destino_farmacia": destino_farmacia,
        "mapas": {
            "google": f"https://www.google.com/maps/dir/?api=1&destination={principal}&travelmode=driving",
            "waze": f"https://waze.com/ul?q={principal}&navigate=yes",
            "apple": f"https://maps.apple.com/?daddr={principal}",
            "google_farmacia_cliente": (
                "https://www.google.com/maps/dir/?api=1"
                f"&destination={cliente_destino}&waypoints={farmacia_destino}&travelmode=driving"
            ),
        },
    }


def _pagamento_texto(entrega: Entrega) -> str:
    valor = f"R$ {entrega.valor_cobrar:.2f}" if entrega.valor_cobrar is not None else ""
    if entrega.forma_pagamento == "dinheiro":
        troco = f" - troco para R$ {entrega.valor_troco:.2f}" if entrega.valor_troco is not None else ""
        return f"COBRAR{f' {valor}' if valor else ''} EM DINHEIRO{troco}"
    if entrega.forma_pagamento == "cartao":
        return f"COBRAR{f' {valor}' if valor else ''} NO CARTÃO (levar maquininha)"
    if entrega.forma_pagamento == "pix":
        return "JÁ PAGO (Pix)"
    if entrega.forma_pagamento == "convenio":
        return "CONVÊNIO: coletar assinatura na nota"
    return "JÁ PAGO"


def _cancelada_json(entrega: Entrega) -> dict:
    return {
        "id": entrega.id,
        "bairro": entrega.bairro_entrega,
        "motivo": entrega.motivo_cancelamento or "Não informado",
    }


def _devolvida_json(entrega: Entrega) -> dict:
    return {
        "id": entrega.id,
        "bairro": entrega.bairro_entrega,
        "motivo": entrega.motivo_devolucao or "Não informado",
    }


def _acao_response(ok: bool, mensagem: str, status: int = 200):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({"ok": ok, "mensagem": mensagem}), status
    flash(mensagem, "success" if ok else "error")
    return redirect(url_for("motoboy.dashboard"))
