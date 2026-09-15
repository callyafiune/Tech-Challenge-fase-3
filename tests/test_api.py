"""Testes do contrato HTTP, da privacidade e das métricas da API."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from medical_classifier import api

TEXTO_VALIDO = "O estudo descreve uma condição médica e seus tratamentos."


class PreditorControlado:
    """Substitui somente o modelo para testar o contrato da API sem treinamento."""

    version = "versao-de-teste"
    backend = "onnx"

    def __init__(self, model_dir: Path, backend: str = "onnx") -> None:
        self.model_dir = model_dir
        self.backend = backend
        self.entradas: list[list[str]] = []
        self.threads: list[int] = []

    def predict(self, texts: list[str]) -> np.ndarray:
        self.entradas.append(texts)
        self.threads.append(threading.get_ident())
        return np.asarray([[0.05, 0.1, 0.7, 0.1, 0.05]], dtype=np.float32)


def criar_aplicacao(monkeypatch, tmp_path, predictor=PreditorControlado, **kwargs):
    """Mantém HTTP, validação, serialização e instrumentação reais."""
    monkeypatch.setattr(api, "Predictor", predictor)
    return api.create_app(model_dir=tmp_path, **kwargs)


def amostras_metricas(response):
    """Lê a exposição Prometheus pelo mesmo formato consumido pelo servidor."""
    assert response.status_code == 200
    return [
        sample
        for family in text_string_to_metric_families(response.text)
        for sample in family.samples
    ]


def test_predicao_retorna_classe_probabilidades_e_identificacao(monkeypatch, tmp_path):
    app = criar_aplicacao(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post("/predict", json={"texto": TEXTO_VALIDO})
    assert response.status_code == 200
    body = response.json()
    assert body["classe_id"] == 3
    assert body["classe"] == "Doenças do sistema nervoso"
    assert body["probabilidades"] == pytest.approx(
        {"1": 0.05, "2": 0.1, "3": 0.7, "4": 0.1, "5": 0.05}
    )
    assert body["versao_modelo"] == "versao-de-teste"
    assert body["backend"] == "onnx"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"texto": ""},
        {"texto": " " * 50},
        {"texto": "x" * 19},
        {"texto": "x" * 20_001},
        {"texto": None},
        {"texto": 42},
        {"texto": [TEXTO_VALIDO]},
        {"texto": TEXTO_VALIDO, "campo_extra": "conteudo-sigiloso"},
    ],
)
def test_rejeita_entrada_invalida_sem_refletir_conteudo(monkeypatch, tmp_path, payload):
    app = criar_aplicacao(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post("/predict", json=payload)
    assert response.status_code == 422
    assert "texto" in response.json()["detail"]
    assert "caracteres" in response.json()["detail"]
    assert TEXTO_VALIDO not in response.text
    assert "conteudo-sigiloso" not in response.text
    assert "x" * 19 not in response.text


def test_rejeita_json_malformado_sem_expor_corpo(monkeypatch, tmp_path):
    app = criar_aplicacao(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/predict",
            content='{"texto": "identificador-sigiloso"',
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert "identificador-sigiloso" not in response.text
    assert "texto" in response.json()["detail"]


@pytest.mark.parametrize("tamanho", [20, 20_000])
def test_aceita_limites_apos_remover_espacos(monkeypatch, tmp_path, tamanho):
    app = criar_aplicacao(monkeypatch, tmp_path)
    with TestClient(app) as client:
        app.state.predictor.entradas.clear()
        response = client.post("/predict", json={"texto": "  " + "x" * tamanho + "  "})
        entradas = app.state.predictor.entradas
    assert response.status_code == 200
    assert entradas == [["x" * tamanho]]


@pytest.mark.parametrize("falha", [FileNotFoundError, ValueError, RuntimeError])
def test_modelo_indisponivel_mantem_liveness_e_impede_predicao(monkeypatch, tmp_path, falha):
    class PreditorIndisponivel:
        def __init__(self, model_dir, backend):
            raise falha("caminho-ou-conteudo-sigiloso")

    app = criar_aplicacao(monkeypatch, tmp_path, predictor=PreditorIndisponivel)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        ready = client.get("/ready")
        response = client.post("/predict", json={"texto": TEXTO_VALIDO})
    assert ready.status_code == 503
    assert response.status_code == 503
    assert "indisponível" in response.json()["detail"]
    assert "sigiloso" not in ready.text + response.text


def test_modelo_carrega_uma_vez_e_executa_fora_do_event_loop(monkeypatch, tmp_path):
    carregamentos = []

    class PreditorUnico(PreditorControlado):
        def __init__(self, model_dir, backend):
            carregamentos.append(model_dir)
            super().__init__(model_dir, backend)

    app = criar_aplicacao(monkeypatch, tmp_path, predictor=PreditorUnico)

    @app.get("/thread-do-loop")
    async def thread_do_loop():
        return {"thread": threading.get_ident()}

    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        thread_loop = client.get("/thread-do-loop").json()["thread"]
        for _ in range(2):
            assert client.post("/predict", json={"texto": TEXTO_VALIDO}).status_code == 200
        assert len(app.state.predictor.threads) == 3
        assert thread_loop not in app.state.predictor.threads
    assert carregamentos == [tmp_path]


def test_falha_de_inferencia_retorna_erro_sem_expor_texto(monkeypatch, tmp_path, caplog):
    class PreditorComFalha(PreditorControlado):
        def predict(self, texts):
            if texts == [TEXTO_VALIDO]:
                raise RuntimeError(texts[0])
            return super().predict(texts)

    app = criar_aplicacao(monkeypatch, tmp_path, predictor=PreditorComFalha)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/predict", json={"texto": TEXTO_VALIDO})
        samples = amostras_metricas(client.get("/metrics"))
    assert response.status_code == 500
    assert "processar" in response.json()["detail"]
    assert TEXTO_VALIDO not in response.text + caplog.text
    assert any(
        sample.name == "http_requests_total"
        and sample.labels == {"method": "POST", "route": "/predict", "status": "500"}
        and sample.value == 1
        for sample in samples
    )


def test_metricas_contam_sucesso_validacao_indisponibilidade_e_rotas_desconhecidas(
    monkeypatch, tmp_path
):
    app = criar_aplicacao(monkeypatch, tmp_path)
    with TestClient(app) as client:
        client.get("/health")
        client.post("/predict", json={"texto": TEXTO_VALIDO})
        client.post("/predict", json={"texto": "curto"})
        client.get("/rota-privada-a")
        client.get("/rota-privada-b")
        client.request("METODO_A", "/health")
        client.request("METODO_B", "/health")
        app.state.predictor = None
        client.post("/predict", json={"texto": TEXTO_VALIDO})
        client.get("/metrics")
        samples = amostras_metricas(client.get("/metrics"))
    contadores = {
        (sample.labels["method"], sample.labels["route"], sample.labels["status"]): sample.value
        for sample in samples
        if sample.name == "http_requests_total"
    }
    assert contadores == {
        ("GET", "/health", "200"): 1,
        ("POST", "/predict", "200"): 1,
        ("POST", "/predict", "422"): 1,
        ("POST", "/predict", "503"): 1,
        ("GET", "/outra", "404"): 2,
        ("OUTRO", "/health", "405"): 2,
    }
    duracoes = [
        sample for sample in samples if sample.name == "http_request_duration_seconds_count"
    ]
    assert sum(sample.value for sample in duracoes) == 8
    assert all(sample.labels["route"] != "/metrics" for sample in duracoes)


def test_metricas_registram_falha_inesperada_do_servidor(monkeypatch, tmp_path):
    app = criar_aplicacao(monkeypatch, tmp_path)

    @app.get("/falha-controlada")
    def falha_controlada():
        raise RuntimeError("detalhe-sigiloso")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/falha-controlada")
        samples = amostras_metricas(client.get("/metrics"))
    assert response.status_code == 500
    assert "detalhe-sigiloso" not in response.text
    assert any(
        sample.name == "http_requests_total"
        and sample.labels == {"method": "GET", "route": "/falha-controlada", "status": "500"}
        and sample.value == 1
        for sample in samples
    )


def test_aplicacoes_tem_registradores_de_metricas_independentes(monkeypatch, tmp_path):
    app_a = criar_aplicacao(monkeypatch, tmp_path)
    app_b = criar_aplicacao(monkeypatch, tmp_path)
    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        client_a.get("/health")
        samples = amostras_metricas(client_b.get("/metrics"))
    assert not any(sample.name == "http_requests_total" for sample in samples)


@pytest.mark.parametrize("disponivel", [True, False])
def test_metrica_model_ready_reflete_disponibilidade(monkeypatch, tmp_path, disponivel):
    class PreditorOpcional(PreditorControlado):
        def __init__(self, model_dir, backend):
            if not disponivel:
                raise FileNotFoundError("Modelo ausente.")
            super().__init__(model_dir, backend)

    app = criar_aplicacao(monkeypatch, tmp_path, predictor=PreditorOpcional)
    with TestClient(app) as client:
        samples = amostras_metricas(client.get("/metrics"))
    readiness = [sample.value for sample in samples if sample.name == "model_ready"]
    assert readiness == [1 if disponivel else 0]


def test_configuracao_por_ambiente_e_argumentos_explicitos(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "Predictor", PreditorControlado)
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "do-ambiente"))
    monkeypatch.setenv("MODEL_BACKEND", "sklearn")
    with TestClient(api.create_app()) as client:
        response = client.post("/predict", json={"texto": TEXTO_VALIDO})
        assert response.json()["backend"] == "sklearn"
        assert client.app.state.predictor.model_dir == tmp_path / "do-ambiente"
    with TestClient(api.create_app(model_dir=tmp_path, backend="onnx")) as client:
        response = client.post("/predict", json={"texto": TEXTO_VALIDO})
        assert response.json()["backend"] == "onnx"
        assert client.app.state.predictor.model_dir == tmp_path


@pytest.mark.parametrize(
    "probabilidades",
    [
        [[0.2, 0.2, 0.2, 0.4]],
        [[float("nan"), 0.2, 0.2, 0.2, 0.2]],
        [[-0.1, 0.2, 0.3, 0.3, 0.3]],
        [[1.1, 0, 0, 0, 0]],
        [[0.1, 0.1, 0.1, 0.1, 0.1]],
    ],
)
def test_aquecimento_impede_readiness_com_saida_invalida(monkeypatch, tmp_path, probabilidades):
    class PreditorInvalido(PreditorControlado):
        def predict(self, texts):
            return np.asarray(probabilidades)

    app = criar_aplicacao(monkeypatch, tmp_path, predictor=PreditorInvalido)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.post("/predict", json={"texto": TEXTO_VALIDO}).status_code == 503


def test_falha_de_carga_registra_tipo_sem_mensagem_sigilosa(monkeypatch, tmp_path, caplog):
    class PreditorIndisponivel:
        def __init__(self, model_dir, backend):
            raise ValueError("caminho-e-texto-sigiloso")

    app = criar_aplicacao(monkeypatch, tmp_path, predictor=PreditorIndisponivel)
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 503
    assert "ValueError" in caplog.text
    assert "caminho-e-texto-sigiloso" not in caplog.text
    assert not any(record.exc_info for record in caplog.records)


def test_probes_respondem_com_pool_de_inferencia_saturado(monkeypatch, tmp_path):
    import anyio
    import httpx

    app = criar_aplicacao(monkeypatch, tmp_path)

    async def verificar():
        async with app.router.lifespan_context(app):
            limiter = anyio.to_thread.current_default_thread_limiter()
            anterior = limiter.total_tokens
            limiter.total_tokens = 1
            ocupante = object()
            await limiter.acquire_on_behalf_of(ocupante)
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://teste"
                ) as client:
                    with anyio.fail_after(0.5):
                        assert (await client.get("/health")).status_code == 200
                        assert (await client.get("/ready")).status_code == 200
            finally:
                limiter.release_on_behalf_of(ocupante)
                limiter.total_tokens = anterior

    asyncio.run(verificar())


def test_docs_identificadas_e_scrape_com_prefixo_nao_e_contado(monkeypatch, tmp_path):
    app = criar_aplicacao(monkeypatch, tmp_path)
    app.root_path = "/medico"
    with TestClient(app, root_path="/medico") as client:
        assert client.get("/medico/docs").status_code == 200
        samples = amostras_metricas(client.get("/medico/metrics"))
        samples = amostras_metricas(client.get("/medico/metrics/"))
    contadores = [sample for sample in samples if sample.name == "http_requests_total"]
    assert len(contadores) == 1
    assert contadores[0].labels == {"method": "GET", "route": "/docs", "status": "200"}
    assert contadores[0].value == 1


def test_identifica_modelo_aquecido_sem_criar_metricas_de_predicao(monkeypatch, tmp_path):
    app = criar_aplicacao(monkeypatch, tmp_path)
    with TestClient(app) as client:
        samples = amostras_metricas(client.get("/metrics"))
    assert any(
        sample.name == "model_info"
        and sample.labels == {"versao": "versao-de-teste", "backend": "onnx"}
        for sample in samples
    )
    assert not any(sample.name == "http_requests_total" for sample in samples)


@pytest.mark.parametrize("fragmentado", [False, True])
def test_limita_corpo_antes_do_parse_inclusive_sem_content_length(
    monkeypatch, tmp_path, fragmentado
):
    import httpx

    app = criar_aplicacao(monkeypatch, tmp_path)

    async def verificar():
        async def partes():
            for _ in range(5):
                yield b"x" * 32_768

        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://teste"
            ) as client:
                body = partes() if fragmentado else b"x" * 131_073
                response = await client.post("/predict", content=body)
                assert response.status_code == 413
                assert "limite" in response.json()["detail"]
                assert "xxxx" not in response.text
                metrics = await client.get("/metrics")
                samples = amostras_metricas(metrics)
                assert any(
                    sample.name == "http_requests_total"
                    and sample.labels == {"method": "POST", "route": "/predict", "status": "413"}
                    and sample.value == 1
                    for sample in samples
                )

    asyncio.run(verificar())


def test_api_carrega_artefato_real_e_classifica_apos_aquecimento(tmp_path):
    import json

    import pandas as pd

    from medical_classifier.training import fit_release, promote_release, write_json

    palavras = ["tumor cancer", "stomach bowel", "brain nerve", "heart artery", "fever pain"]
    frame = pd.DataFrame(
        [
            {"condition_label": i + 1, "medical_abstract": f"clinical study {palavra} " * n}
            for i, palavra in enumerate(palavras)
            for n in range(1, 5)
        ]
    )
    release = fit_release(frame, frame, tmp_path, {"origem": "teste sintético"})
    metadata = json.loads((release / "metadata.json").read_text("utf-8"))
    # Evidências sintéticas vinculadas: este teste verifica o carregamento pela API.
    write_json(
        release / "avaliacao.json",
        {"aprovado": True, "versao_modelo": release.name, "sha256_modelos": metadata["sha256"]},
    )
    write_json(
        release / "latencia.json", {"fator_aceleracao_p50": 2.0, "versao_modelo": release.name}
    )
    promote_release(release, tmp_path)
    with TestClient(api.create_app(model_dir=tmp_path)) as client:
        assert client.get("/ready").status_code == 200
        response = client.post("/predict", json={"texto": "clinical study heart artery treatment"})
    assert response.status_code == 200
    assert response.json()["classe_id"] == 4
    assert response.json()["backend"] == "onnx"
    assert sum(response.json()["probabilidades"].values()) == pytest.approx(1)


def test_desconexao_durante_leitura_e_contada_como_499(monkeypatch, tmp_path):
    import httpx

    app = criar_aplicacao(monkeypatch, tmp_path)

    async def verificar():
        eventos = iter(
            [
                {"type": "http.request", "body": b'{"texto":', "more_body": True},
                {"type": "http.disconnect"},
            ]
        )
        respostas = []

        async def receber():
            return next(eventos)

        async def enviar(evento):
            respostas.append(evento)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "POST",
            "path": "/predict",
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("teste", 80),
            "client": ("127.0.0.1", 1234),
        }
        async with app.router.lifespan_context(app):
            await app(scope, receber, enviar)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://teste"
            ) as client:
                samples = amostras_metricas(await client.get("/metrics"))
        assert respostas == []
        contadores = [sample for sample in samples if sample.name == "http_requests_total"]
        assert len(contadores) == 1
        assert contadores[0].labels == {"method": "POST", "route": "/predict", "status": "499"}

    asyncio.run(verificar())
