"""Testes rápidos das validações e do isolamento de clientes."""

from app.utils.validators import normalize_cpf, normalize_phone


assert normalize_cpf("529.982.247-25") == "52998224725"
assert normalize_phone("(47) 99999-1234") == "47999991234"
for valor in ("11111111111", "52998224724", "123"):
    try:
        normalize_cpf(valor)
    except ValueError:
        pass
    else:
        raise AssertionError(f"CPF inválido aceito: {valor}")

print("Validações de CPF e telefone OK.")
