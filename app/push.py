from flask import current_app
from app.models import Entrega


def notificar_motoboys(entrega: Entrega) -> None:
    current_app.logger.info(
        "Notificação de nova entrega pendente (stub): entrega_id=%s",
        entrega.id,
    )
