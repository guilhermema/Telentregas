from datetime import datetime

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import update

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
    entregas = Entrega.query.filter_by(status="pendente").order_by(Entrega.data_criacao.asc()).all()
    return jsonify({"entregas": [_praca_json(entrega) for entrega in entregas]})


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
        flash("Esta corrida já foi aceita por outro motoboy", "error")
    else:
        flash("Corrida aceita.", "success")
    return redirect(url_for("motoboy.dashboard"))


@motoboy_bp.post("/entregas/<int:entrega_id>/avancar")
@role_required("motoboy")
def avancar(entrega_id: int):
    motoboy = _motoboy_logado()
    entrega = Entrega.query.filter_by(id=entrega_id, motoboy_id=motoboy.id).first_or_404()
    proximo = {"aceita": ("coletada", "data_coleta"), "coletada": ("entregue", "data_entrega")}
    destino = proximo.get(entrega.status)
    if destino is None:
        flash("Esta corrida não pode avançar a partir do status atual.", "error")
        return redirect(url_for("motoboy.dashboard"))

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
        flash("A corrida foi atualizada. Recarregue a lista.", "error")
    else:
        flash(f"Status atualizado para {status_novo}.", "success")
    return redirect(url_for("motoboy.dashboard"))


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
    return {
        "id": entrega.id,
        "bairro": entrega.bairro_entrega,
        "valor_taxa": f"{entrega.valor_taxa:.2f}",
        "precisa_troco": entrega.precisa_troco,
        "valor_troco": f"{entrega.valor_troco:.2f}" if entrega.valor_troco is not None else None,
        "usa_maquininha": entrega.usa_maquininha,
        "farmacia": entrega.farmacia.razao_social,
    }
