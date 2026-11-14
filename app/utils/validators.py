import re
import unicodedata


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_phone(value: str | None) -> str:
    value = digits(value)
    if len(value) not in (10, 11):
        raise ValueError("Informe um telefone válido com DDD (10 ou 11 dígitos).")
    return value


def normalize_cpf(value: str | None) -> str:
    value = digits(value)
    if len(value) != 11 or len(set(value)) == 1:
        raise ValueError("Informe um CPF válido.")
    total = sum(int(value[i]) * (10 - i) for i in range(9))
    first = (total * 10) % 11
    first = 0 if first == 10 else first
    total = sum(int(value[i]) * (11 - i) for i in range(10))
    second = (total * 10) % 11
    second = 0 if second == 10 else second
    if value[-2:] != f"{first}{second}":
        raise ValueError("Informe um CPF válido.")
    return value


def normalize_text(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.casefold().split())


def mask_cpf(value: str) -> str:
    value = digits(value)
    return f"***.{value[3:6]}.{value[6:9]}-**" if len(value) == 11 else "***.***.***-**"
