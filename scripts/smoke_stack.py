"""Valida a stack em execução e grava evidências sem textos ou credenciais."""

from __future__ import annotations

import argparse
import base64
import json
import math
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

RAIZ = Path(__file__).resolve().parents[1]
TEXTO_EXEMPLO = (
    "Patients with coronary artery disease underwent cardiac evaluation. "
    "The study assessed myocardial infarction and cardiovascular treatment outcomes."
)


def consultar(
    url: str, corpo: dict[str, Any] | None = None, cabecalhos: dict[str, str] | None = None
) -> tuple[int, Any]:
    """Consulta HTTP com prazo explícito, incluindo respostas de erro esperadas."""
    headers = dict(cabecalhos or {})
    dados = None
    if corpo is not None:
        dados = json.dumps(corpo).encode("utf-8")
        headers["Content-Type"] = "application/json"
    pedido = Request(url, data=dados, headers=headers)
    try:
        resposta = urlopen(pedido, timeout=10)
    except HTTPError as erro:
        resposta = erro
    with resposta:
        conteudo = resposta.read().decode("utf-8")
        if "application/json" in resposta.headers.get("Content-Type", ""):
            return resposta.status, json.loads(conteudo)
        return resposta.status, conteudo


def exigir(condicao: bool, mensagem: str) -> None:
    """Interrompe a verificação sem depender da opção de otimização do Python."""
    if not condicao:
        raise RuntimeError(mensagem)


def aguardar(verificacao: Callable[[], Any], descricao: str, prazo: float) -> Any:
    """Aguarda condição real, respeitando o intervalo de coleta do Prometheus."""
    limite = time.monotonic() + prazo
    while time.monotonic() < limite:
        try:
            resultado = verificacao()
            if resultado:
                return resultado
        except (URLError, OSError):
            pass
        time.sleep(1)
    raise RuntimeError(f"Tempo esgotado aguardando {descricao}.")


def carregar_configuracao() -> dict[str, Any]:
    """Obtém variáveis resolvidas pelo Compose sem imprimir suas credenciais."""
    processo = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if processo.returncode != 0:
        # Classifica a causa sem copiar saídas que possam conter valores de segredos.
        if "GRAFANA_ADMIN_PASSWORD" in processo.stderr:
            mensagem = "Defina GRAFANA_ADMIN_PASSWORD no arquivo .env antes de executar o smoke."
        elif "yaml" in processo.stderr.lower():
            mensagem = (
                "Configuração YAML inválida; confira a sintaxe do arquivo docker-compose.yml."
            )
        else:
            mensagem = (
                f"Falha ao ler o Compose (código {processo.returncode}). "
                "Confira a instalação do Docker e execute docker compose config --quiet."
            )
        raise RuntimeError(mensagem)
    return json.loads(processo.stdout)


def endereco(configuracao: dict[str, Any], servico: str, porta: int) -> str:
    """Encontra a porta publicada, inclusive quando alterada pelo arquivo .env."""
    for item in configuracao["services"][servico]["ports"]:
        if item["target"] == porta:
            return f"http://127.0.0.1:{item['published']}"
    raise RuntimeError(f"Porta de {servico} não encontrada no Compose.")


def consultar_prometheus(
    url: str, expressao: str, instante: float | None = None
) -> list[dict[str, Any]]:
    """Executa PromQL na API real; rejeita expressões inválidas e respostas de erro."""
    parametros: dict[str, str | float] = {"query": expressao}
    if instante is not None:
        parametros["time"] = instante
    status, corpo = consultar(f"{url}/api/v1/query?{urlencode(parametros)}")
    exigir(status == 200 and corpo.get("status") == "success", "Consulta PromQL falhou.")
    return corpo["data"]["result"]


def valor_metrica(url: str, expressao: str, instante: float | None = None) -> float:
    """Retorna a primeira série escalar ou NaN quando ainda não houve coleta."""
    series = consultar_prometheus(url, expressao, instante)
    return float(series[0]["value"][1]) if series else math.nan


def consultar_grafana(url: str, cabecalhos: dict[str, str]) -> tuple[int, Any]:
    """Distingue credenciais e permissões de uma falha na fonte de dados."""
    status, corpo = consultar(url, cabecalhos=cabecalhos)
    if status == 401:
        raise RuntimeError(
            "O Grafana recusou as credenciais (HTTP 401). Confira o usuário e a senha "
            "persistidos no volume; alterar apenas .env não redefine a senha existente."
        )
    if status == 403:
        raise RuntimeError(
            "A conta do Grafana não possui permissão para esta verificação (HTTP 403). "
            "Use uma conta com acesso à fonte de dados e ao dashboard."
        )
    return status, corpo


def executar(argumentos: argparse.Namespace) -> dict[str, Any]:
    """Verifica API, coleta, fonte de dados e consultas de todos os painéis."""
    config = carregar_configuracao()
    api = endereco(config, "api", 8000)
    prometheus = endereco(config, "prometheus", 9090)
    grafana = endereco(config, "grafana", 3000)
    prazo = argumentos.tempo_limite
    aguardar(lambda: consultar(f"{api}/ready")[0] == 200, "prontidão da API", prazo)
    exigir(consultar(f"{api}/health")[0] == 200, "Liveness da API falhou.")
    status, previsao = consultar(f"{api}/predict", {"texto": TEXTO_EXEMPLO})
    exigir(status == 200, "A primeira classificação não retornou HTTP 200.")
    exigir(previsao.get("classe_id") in range(1, 6), "Classe fora do corpus esperado.")
    probabilidades = previsao.get("probabilidades", {})
    exigir(
        set(probabilidades) == {"1", "2", "3", "4", "5"}
        and all(0 <= p <= 1 for p in probabilidades.values())
        and abs(sum(probabilidades.values()) - 1) < 0.001,
        "Probabilidades inválidas na resposta da API.",
    )
    exigir(
        consultar(f"{api}/predict", {"texto": ""})[0] == 422,
        "A API não rejeitou a entrada vazia com HTTP 422.",
    )
    filtro = 'job="medical-api",route="/predict",method="POST",status="200"'
    contador = f"sum(http_requests_total{{{filtro}}})"
    filtro_erros = 'job="medical-api",route="/predict",method="POST",status="422"'
    contador_erros = f"sum(http_requests_total{{{filtro_erros}}})"
    aguardar(lambda: consultar(f"{prometheus}/-/ready")[0] == 200, "Prometheus", prazo)
    aguardar(
        lambda: valor_metrica(prometheus, contador) >= 1
        and valor_metrica(prometheus, contador_erros) >= 1,
        "primeira coleta de classificação",
        prazo,
    )
    inicial = valor_metrica(prometheus, contador)
    erros_iniciais = valor_metrica(prometheus, contador_erros)
    # A carga espaçada atravessa coletas de 5 s e mantém dados na janela mínima de 20 s.
    for _ in range(argumentos.requisicoes):
        exigir(
            consultar(f"{api}/predict", {"texto": TEXTO_EXEMPLO})[0] == 200,
            "Falha durante as classificações de demonstração.",
        )
        time.sleep(1)
    exigir(
        consultar(f"{api}/predict", {"texto": ""})[0] == 422,
        "A segunda entrada inválida não retornou HTTP 422.",
    )

    def coleta_completa() -> float | None:
        if not valor_metrica(prometheus, contador) >= inicial + argumentos.requisicoes:
            return None
        if not valor_metrica(prometheus, contador_erros) >= erros_iniciais + 1:
            return None
        series = consultar_prometheus(
            prometheus, f"sum(rate(http_requests_total{{{filtro_erros}}}[20s]))"
        )
        if series and float(series[0]["value"][1]) > 0:
            return float(series[0]["value"][0])
        return None

    # Todas as consultas usam o instante em que a coleta foi confirmada pelo servidor.
    # Assim, esperar o Grafana não faz a janela de taxa perder as chamadas produzidas.
    instante_metricas = aguardar(
        coleta_completa,
        "coleta das novas classificações",
        prazo,
    )
    status, metricas = consultar(f"{api}/metrics")
    exigir(
        status == 200
        and "http_requests_total" in metricas
        and "http_request_duration_seconds_bucket" in metricas,
        "Contador ou histograma HTTP não foi exposto.",
    )
    exigir(
        valor_metrica(prometheus, 'up{job="medical-api"}') == 1,
        "Prometheus não consegue coletar a API.",
    )
    exigir(
        valor_metrica(prometheus, 'model_ready{job="medical-api"}') == 1,
        "A métrica de prontidão do modelo não está ativa.",
    )
    aguardar(lambda: consultar(f"{grafana}/api/health")[0] == 200, "Grafana", prazo)
    ambiente = config["services"]["grafana"]["environment"]
    credencial = (
        f"{ambiente['GF_SECURITY_ADMIN_USER']}:{ambiente['GF_SECURITY_ADMIN_PASSWORD']}"
    ).encode()
    cabecalhos = {"Authorization": f"Basic {base64.b64encode(credencial).decode('ascii')}"}
    status, saude = consultar_grafana(
        f"{grafana}/api/datasources/uid/prometheus-medical/health", cabecalhos
    )
    exigir(
        status == 200 and saude.get("status") == "OK",
        "A fonte de dados do Grafana não alcança o Prometheus.",
    )
    status, dashboard = consultar_grafana(
        f"{grafana}/api/dashboards/uid/medical-classifier", cabecalhos
    )
    exigir(status == 200, "Dashboard provisionado não foi encontrado no Grafana.")
    paineis = dashboard["dashboard"]["panels"]
    exigir(len(paineis) >= 3, "O dashboard tem menos de três painéis.")
    evidencias_paineis = []
    for painel in paineis:
        consultas = []
        for alvo in painel.get("targets", []):
            expressao = alvo["expr"].replace("$__rate_interval", "20s")
            valor = valor_metrica(prometheus, expressao, instante_metricas)
            exigir(
                math.isfinite(valor),
                f"O painel {painel['title']} não possui dados finitos no instante verificado.",
            )
            consultas.append(
                {
                    "expressao": expressao,
                    "valor": valor,
                }
            )
        exigir(bool(consultas), f"Painel sem consulta: {painel['title']}.")
        evidencias_paineis.append({"titulo": painel["title"], "consultas": consultas})
    return {
        "sucesso": True,
        "api": {"health": 200, "ready": 200, "predict": 200, "entrada_invalida": 422},
        "modelo": {"versao": previsao["versao_modelo"], "backend": previsao["backend"]},
        "requisicoes_validas_geradas": argumentos.requisicoes + 1,
        "prometheus": {
            "coleta": "ativa",
            "histograma": "presente",
            "janela_taxa": "20s",
            "instante_metricas_utc": datetime.fromtimestamp(instante_metricas, UTC).isoformat(),
        },
        "grafana": {
            "fonte_dados": "OK",
            "dashboard": "medical-classifier",
            "paineis": evidencias_paineis,
        },
    }


def main() -> int:
    """Grava o resultado da execução e retorna código não zero quando houver falha."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requisicoes", type=int, default=20, help="Chamadas válidas após a coleta inicial."
    )
    parser.add_argument(
        "--tempo-limite", type=float, default=90, help="Espera máxima por condição, em segundos."
    )
    parser.add_argument("--saida", type=Path, default=RAIZ / "reports" / "smoke_stack.json")
    argumentos = parser.parse_args()
    if argumentos.requisicoes < 1 or argumentos.tempo_limite <= 0:
        parser.error("Informe pelo menos uma requisição e um tempo limite positivo.")
    inicio = datetime.now(UTC).isoformat()
    try:
        resultado = executar(argumentos)
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as erro:
        resultado = {"sucesso": False, "erro": str(erro)}
    resultado["inicio_utc"] = inicio
    resultado["fim_utc"] = datetime.now(UTC).isoformat()
    argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
    serializado = json.dumps(resultado, ensure_ascii=False, indent=2, allow_nan=False)
    argumentos.saida.write_text(serializado + "\n", encoding="utf-8")
    print(serializado)
    return 0 if resultado["sucesso"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
