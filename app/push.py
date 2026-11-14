import json
from flask import current_app
from threading import Thread

from pywebpush import WebPushException, webpush

from app.extensions import db
from app.models import Entrega


def vapid_public_key() -> str:
    return current_app.config["VAPID_PUBLIC_KEY"]


def notificar_motoboys(entrega: Entrega) -> None:
    app = current_app._get_current_object()
    subscriptions = [
        {
            "id": subscription.id,
            "endpoint": subscription.endpoint,
            "p256dh": subscription.p256dh,
            "auth": subscription.auth,
        }
        for subscription in _subscriptions_ativas()
    ]
    payload = {
        "title": "Nova entrega!",
        "body": f"{entrega.bairro_entrega} · R$ {entrega.valor_taxa:.2f}",
        "url": "/motoboy/",
    }
    Thread(
        target=_enviar_pushes,
        args=(app, subscriptions, payload),
        daemon=True,
        name="push-motoboys",
    ).start()
    app.logger.info("Push enfileirado: entrega_id=%s destinatarios=%s", entrega.id, len(subscriptions))


def notificar_cancelamento(entrega: Entrega, motoboy_id: int) -> None:
    app = current_app._get_current_object()
    from app.models import Motoboy

    motoboy = db.session.get(Motoboy, motoboy_id)
    subscriptions = []
    if motoboy:
        subscriptions = [
            {"id": item.id, "endpoint": item.endpoint, "p256dh": item.p256dh, "auth": item.auth}
            for item in motoboy.user.push_subscriptions
        ]
    payload = {
        "title": "Corrida cancelada",
        "body": f"{entrega.bairro_entrega} - {entrega.motivo_cancelamento or 'Sem motivo'}",
        "url": "/motoboy/",
    }
    Thread(target=_enviar_pushes, args=(app, subscriptions, payload), daemon=True, name="push-cancelamento").start()


def _subscriptions_ativas():
    from app.models import PushSubscription, User

    return PushSubscription.query.join(User).filter(User.role == "motoboy", User.ativo.is_(True)).all()


def _enviar_pushes(app, subscriptions, payload) -> None:
    with app.app_context():
        claim_email = str(app.config.get("VAPID_CLAIM_EMAIL", "")).strip()
        if not claim_email:
            app.logger.error(
                "Web Push não enviado: VAPID_CLAIM_EMAIL está vazio. "
                "Configure uma URL mailto: no arquivo .env."
            )
            return
        if not claim_email.lower().startswith("mailto:"):
            app.logger.error(
                "Web Push não enviado: VAPID_CLAIM_EMAIL deve começar com "
                "'mailto:'. Valor configurado é inválido."
            )
            return

        for subscription in subscriptions:
            try:
                # pywebpush pode alterar o dicionário recebido; não reutilizar claims.
                vapid_claims = {"sub": claim_email}
                webpush(
                    subscription_info={
                        "endpoint": subscription["endpoint"],
                        "keys": {
                            "p256dh": subscription["p256dh"],
                            "auth": subscription["auth"],
                        },
                    },
                    data=json.dumps(payload),
                    vapid_private_key=app.config["VAPID_PRIVATE_KEY"],
                    vapid_claims=vapid_claims,
                    headers={"Urgency": "high"},
                )
            except WebPushException as error:
                status_code = getattr(getattr(error, "response", None), "status_code", None)
                if status_code in (404, 410):
                    PushSubscription.query.filter_by(id=subscription["id"]).delete()
                    db.session.commit()
                    app.logger.info("Subscription removida: id=%s status=%s", subscription["id"], status_code)
                else:
                    app.logger.exception("Falha ao enviar push: subscription_id=%s", subscription["id"])
            except Exception:
                app.logger.exception("Erro inesperado no envio de push: subscription_id=%s", subscription["id"])
