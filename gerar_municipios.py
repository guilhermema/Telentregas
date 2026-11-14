"""Baixa uma vez os estados e municípios do IBGE para uso offline no navegador."""

import gzip
import json
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://servicodados.ibge.gov.br/api/v1/localidades"
OUTPUT = Path(__file__).parent / "app" / "static" / "data" / "municipios.json"


def obter_json(url: str):
    request = Request(url, headers={"Accept-Encoding": "gzip"})
    with urlopen(request, timeout=60) as response:
        content = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            content = gzip.decompress(content)
    return json.loads(content)


def main() -> None:
    estados_api = obter_json(f"{BASE_URL}/estados")
    estados = [
        {"sigla": estado["sigla"], "nome": estado["nome"]}
        for estado in sorted(estados_api, key=lambda item: item["sigla"])
    ]
    municipios = {}
    for estado in estados:
        cidades = obter_json(f"{BASE_URL}/estados/{estado['sigla']}/municipios")
        municipios[estado["sigla"]] = [cidade["nome"] for cidade in cidades]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"estados": estados, "municipios": municipios}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Dados do IBGE salvos em {OUTPUT} ({len(estados)} estados).")


if __name__ == "__main__":
    main()
