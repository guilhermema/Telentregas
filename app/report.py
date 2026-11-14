from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.models import Entrega

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MAX_PERIOD_DAYS = 366


def parse_report_dates(data_de: str | None, data_ate: str | None) -> tuple[date, date]:
    if not data_de or not data_ate:
        raise ValueError("Informe as datas De e Até.")
    try:
        inicio = datetime.strptime(data_de, "%Y-%m-%d").date()
        fim = datetime.strptime(data_ate, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("Informe datas válidas.") from error
    if inicio > fim:
        raise ValueError("A data De não pode ser maior que a data Até.")
    if (fim - inicio).days + 1 > MAX_PERIOD_DAYS:
        raise ValueError("O período máximo do relatório é de 366 dias.")
    return inicio, fim


def period_bounds(inicio: date, fim: date) -> tuple[datetime, datetime]:
    inicio_local = datetime.combine(inicio, time.min, tzinfo=SAO_PAULO)
    fim_local = datetime.combine(fim + timedelta(days=1), time.min, tzinfo=SAO_PAULO)
    return inicio_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None), fim_local.astimezone(
        ZoneInfo("UTC")
    ).replace(tzinfo=None)


def delivered_query(farmacia_id: int, inicio: date, fim: date):
    inicio_utc, fim_utc = period_bounds(inicio, fim)
    return Entrega.query.filter(
        Entrega.farmacia_id == farmacia_id,
        Entrega.status == "entregue",
        Entrega.data_entrega.is_not(None),
        Entrega.data_entrega >= inicio_utc,
        Entrega.data_entrega < fim_utc,
    )


def history_query(farmacia_id: int, inicio: date, fim: date, mostrar_canceladas: bool):
    inicio_utc, fim_utc = period_bounds(inicio, fim)
    query = Entrega.query.filter(Entrega.farmacia_id == farmacia_id)
    delivered = (Entrega.status == "entregue") & (
        Entrega.data_entrega.is_not(None)
    ) & (Entrega.data_entrega >= inicio_utc) & (Entrega.data_entrega < fim_utc)
    if mostrar_canceladas:
        cancelled = (Entrega.status == "cancelada") & (
            Entrega.data_cancelamento.is_not(None)
        ) & (Entrega.data_cancelamento >= inicio_utc) & (Entrega.data_cancelamento < fim_utc)
        return query.filter(delivered | cancelled)
    return query.filter(delivered)


def report_data(entregas: list[Entrega]) -> tuple[list[dict], Decimal]:
    rows = []
    subtotals = defaultdict(lambda: {"quantidade": 0, "valor": Decimal("0.00")})
    for entrega in entregas:
        valor = Decimal(entrega.valor_taxa)
        nome = entrega.nome_cliente.strip().split()[0] if entrega.nome_cliente.strip() else ""
        rows.append(
            {
                "data": _local_datetime(entrega.data_entrega).strftime("%d/%m/%Y %H:%M"),
                "bairro": entrega.bairro_entrega,
                "cliente": nome,
                "taxa": valor,
                "motoboy": entrega.motoboy.nome if entrega.motoboy else "Não informado",
                "coleta": _local_datetime(entrega.data_coleta).strftime("%d/%m/%Y %H:%M")
                if entrega.data_coleta
                else "Não informado",
                "entrega": _local_datetime(entrega.data_entrega).strftime("%d/%m/%Y %H:%M"),
            }
        )
        subtotals[entrega.bairro_entrega]["quantidade"] += 1
        subtotals[entrega.bairro_entrega]["valor"] += valor
    return rows, sum((row["taxa"] for row in rows), Decimal("0.00"))


def cancelled_data(entregas: list[Entrega]) -> list[dict]:
    rows = []
    for entrega in entregas:
        nome = entrega.nome_cliente.strip().split()[0] if entrega.nome_cliente.strip() else ""
        rows.append(
            {
                "data": _local_datetime(entrega.data_cancelamento).strftime("%d/%m/%Y %H:%M"),
                "bairro": entrega.bairro_entrega,
                "cliente": nome,
                "motivo": entrega.motivo_cancelamento or "Não informado",
                "taxa": Decimal(entrega.valor_taxa),
            }
        )
    return rows


def summary_data(entregas: list[Entrega], canceladas: list[Entrega]) -> dict:
    total = sum((Decimal(entrega.valor_taxa) for entrega in entregas), Decimal("0.00"))
    return {
        "entregues": len(entregas),
        "canceladas": len(canceladas),
        "media": total / len(entregas) if entregas else Decimal("0.00"),
        "total": total,
    }


def subtotal_data(entregas: list[Entrega]) -> list[dict]:
    grupos = defaultdict(lambda: {"quantidade": 0, "valor": Decimal("0.00")})
    for entrega in entregas:
        grupos[entrega.bairro_entrega]["quantidade"] += 1
        grupos[entrega.bairro_entrega]["valor"] += Decimal(entrega.valor_taxa)
    return [
        {"bairro": bairro, **valores}
        for bairro, valores in sorted(grupos.items(), key=lambda item: item[0].casefold())
    ]


def brl(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def safe_filename(value: str) -> str:
    normalized = value.encode("ascii", "ignore").decode("ascii")
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in normalized).strip("_") or "farmacia"


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(SAO_PAULO)
