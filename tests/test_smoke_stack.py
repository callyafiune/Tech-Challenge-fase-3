"""Regressões do smoke sem depender do Docker ou de serviços externos."""

import argparse
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import smoke_stack


@pytest.fixture
def servicos(monkeypatch):
    """Simula serviços HTTP e uma demora do Grafana maior que a janela de taxa."""
    estado = SimpleNamespace(
        agora=1_800_000_000.0,
        validas=0,
        invalidas=0,
        ultimo_trafego=0.0,
        atrasou=False,
        status_grafana=200,
        histograma_invalido=False,
        consultas_histograma=[],
    )

    def dormir(segundos):
        estado.agora += segundos

    monkeypatch.setattr(smoke_stack.time, "sleep", dormir)
    monkeypatch.setattr(smoke_stack.time, "monotonic", lambda: estado.agora)
    configuracao = {
        "services": {
            "api": {"ports": [{"target": 8000, "published": "8000"}]},
            "prometheus": {"ports": [{"target": 9090, "published": "9090"}]},
            "grafana": {
                "ports": [{"target": 3000, "published": "3000"}],
                "environment": {
                    "GF_SECURITY_ADMIN_USER": "admin",
                    "GF_SECURITY_ADMIN_PASSWORD": "segredo-do-teste",
                },
            },
        }
    }
    monkeypatch.setattr(smoke_stack, "carregar_configuracao", lambda: configuracao)

    def consultar(url, corpo=None, cabecalhos=None):
        recurso = urlsplit(url)
        if recurso.path in {"/health", "/ready", "/-/ready"}:
            return 200, {}
        if recurso.path == "/predict":
            estado.ultimo_trafego = estado.agora
            if corpo["texto"] == "":
                estado.invalidas += 1
                return 422, {"detail": "Texto vazio."}
            estado.validas += 1
            return 200, {
                "classe_id": 4,
                "probabilidades": {str(classe): 0.2 for classe in range(1, 6)},
                "versao_modelo": "versao-teste",
                "backend": "onnx",
            }
        if recurso.path == "/metrics":
            return 200, "http_requests_total\nhttp_request_duration_seconds_bucket\n"
        if recurso.path == "/api/v1/query":
            parametros = parse_qs(recurso.query)
            expressao = parametros["query"][0]
            instante = float(parametros.get("time", [estado.agora])[0])
            if "histogram_quantile" in expressao:
                estado.consultas_histograma.append((estado.agora, instante))
                valor = (
                    0.005
                    if not estado.histograma_invalido and instante <= estado.ultimo_trafego + 20
                    else float("nan")
                )
            elif "rate(" in expressao:
                valor = 0.5
            elif "http_requests_total" in expressao:
                valor = estado.invalidas if 'status="422"' in expressao else estado.validas
            else:
                valor = 1
            return 200, {
                "status": "success",
                "data": {"result": [{"value": [instante, str(valor)]}]},
            }
        if recurso.path == "/api/health":
            if not estado.atrasou:
                dormir(35)
                estado.atrasou = True
            return 200, {}
        if recurso.path == "/api/datasources/uid/prometheus-medical/health":
            return estado.status_grafana, {"status": "OK", "message": "segredo-do-teste"}
        if recurso.path == "/api/dashboards/uid/medical-classifier":
            expressoes = [
                'sum(http_requests_total{job="medical-api"})',
                'model_ready{job="medical-api"}',
                "histogram_quantile(0.95, "
                "rate(http_request_duration_seconds_bucket[$__rate_interval]))",
            ]
            return 200, {
                "dashboard": {
                    "panels": [
                        {"title": f"Painel {indice}", "targets": [{"expr": expressao}]}
                        for indice, expressao in enumerate(expressoes)
                    ]
                }
            }
        raise AssertionError(f"Recurso inesperado no teste: {recurso.path}")

    monkeypatch.setattr(smoke_stack, "consultar", consultar)
    return estado


def test_preserva_janela_de_metricas_quando_grafana_demora(servicos):
    """O histograma continua consultável após uma espera maior que seus 20 segundos."""
    resultado = smoke_stack.executar(argparse.Namespace(tempo_limite=90, requisicoes=2))
    assert resultado["sucesso"] is True
    assert servicos.consultas_histograma
    for momento_consulta, instante_avaliacao in servicos.consultas_histograma:
        assert momento_consulta - instante_avaliacao >= 35
        assert instante_avaliacao <= servicos.ultimo_trafego + 20


def test_painel_historico_invalido_falha_sem_repetir_consulta(servicos):
    """Uma amostra histórica inválida é determinística e não justifica nova espera."""
    servicos.histograma_invalido = True
    inicio = servicos.agora
    with pytest.raises(RuntimeError, match="Painel 2"):
        smoke_stack.executar(argparse.Namespace(tempo_limite=90, requisicoes=2))
    assert len(servicos.consultas_histograma) == 1
    assert servicos.agora - inicio == 37


@pytest.mark.parametrize("status, explicacao", [(401, "credenciais"), (403, "permissão")])
def test_distingue_autenticacao_do_grafana_de_falha_no_prometheus(servicos, status, explicacao):
    """Erros de acesso orientam sobre credenciais e não divulgam a resposta remota."""
    servicos.status_grafana = status
    with pytest.raises(RuntimeError, match=explicacao) as erro:
        smoke_stack.executar(argparse.Namespace(tempo_limite=90, requisicoes=2))
    assert "segredo-do-teste" not in str(erro.value)
