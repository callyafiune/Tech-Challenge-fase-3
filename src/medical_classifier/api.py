"""API de classificação de resumos médicos com validação e observabilidade."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from medical_classifier.contracts import CLASSES
from medical_classifier.metrics import HttpMetrics, HttpMetricsMiddleware
from medical_classifier.serving import Predictor

LOGGER = logging.getLogger(__name__)


class BodyLimitMiddleware:
    """Limita a leitura do corpo antes do JSON, inclusive em transferência fragmentada."""

    def __init__(self, app: ASGIApp, limit: int = 128 * 1024) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def reject() -> None:
            response = JSONResponse(
                status_code=413, content={"detail": "O corpo excede o limite de 128 KiB."}
            )
            await response(scope, receive, send)

        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    length = int(value)
                except ValueError:
                    length = -1
                if length < 0:
                    response = JSONResponse(
                        status_code=400, content={"detail": "Comprimento do corpo inválido."}
                    )
                    await response(scope, receive, send)
                    return
                if length > self.limit:
                    await reject()
                    return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                scope["medical_client_disconnected"] = True
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.limit:
                await reject()
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def _probabilities(predictor: Predictor, texts: list[str]) -> np.ndarray:
    """Rejeita dimensões ou probabilidades incompatíveis com o contrato das cinco classes."""
    result = np.asarray(predictor.predict(texts))
    if (
        result.shape != (len(texts), len(CLASSES))
        or not np.isfinite(result).all()
        or not ((result >= 0) & (result <= 1)).all()
        or not np.allclose(result.sum(axis=1), 1, atol=1e-5)
    ):
        raise ValueError("O modelo retornou probabilidades inválidas.")
    return result


class PredictionRequest(BaseModel):
    """Aceita um único resumo, sem campos adicionais nem conversão implícita de tipos."""

    model_config = ConfigDict(extra="forbid")
    texto: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=20, max_length=20_000, strict=True),
    ] = Field(
        description=(
            "Resumo médico em inglês, com 20 a 20.000 caracteres sem espaços externos. "
            "O corpo JSON completo tem limite de 128 KiB, incluindo escapes Unicode."
        )
    )


class PredictionResponse(BaseModel):
    """Associa a classe de maior probabilidade à versão efetivamente carregada."""

    classe_id: int
    classe: str
    probabilidades: dict[str, float]
    versao_modelo: str
    backend: str


def create_app(model_dir: Path | None = None, backend: str | None = None) -> FastAPI:
    """Cria a aplicação e carrega uma única versão do modelo durante sua inicialização."""
    selected_dir = Path(model_dir if model_dir is not None else os.getenv("MODEL_DIR", "models"))
    selected_backend = backend if backend is not None else os.getenv("MODEL_BACKEND", "onnx")
    metrics = HttpMetrics()

    def load_predictor() -> Predictor:
        predictor = Predictor(model_dir=selected_dir, backend=selected_backend)
        _probabilities(
            predictor, ["Clinical study about disease diagnosis and treatment outcomes."]
        )
        return predictor

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            predictor = await run_in_threadpool(load_predictor)
            metrics.model_info.labels(predictor.version, predictor.backend).info({})
            application.state.predictor = predictor
        except Exception as error:
            # O tipo ajuda na operação; a mensagem e o traceback podem conter texto sensível.
            LOGGER.error(
                "Modelo indisponível durante carregamento ou aquecimento (%s).",
                type(error).__name__,
            )
            application.state.predictor = None
        try:
            yield
        finally:
            application.state.predictor = None

    application = FastAPI(
        title="Classificador de condições médicas",
        description=(
            "Classifica resumos em inglês nas cinco categorias do Medical Abstracts TC Corpus. "
            "Projeto acadêmico: não realiza diagnóstico, triagem de urgência "
            "nem orientação clínica."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.predictor = None
    metrics.model_ready.set_function(lambda: int(application.state.predictor is not None))
    application.add_middleware(BodyLimitMiddleware)
    application.add_middleware(HttpMetricsMiddleware, metrics=metrics, routes=application.routes)

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": (
                    "Envie um objeto JSON contendo somente o campo 'texto', com uma string entre "
                    "20 e 20.000 caracteres, sem contar espaços nas extremidades."
                )
            },
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, error: StarletteHTTPException):
        details = {404: "Rota não encontrada.", 405: "Método HTTP não permitido nesta rota."}
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": details.get(error.status_code, error.detail)},
            headers=error.headers,
        )

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception):
        return JSONResponse(
            status_code=500, content={"detail": "Não foi possível processar a solicitação."}
        )

    @application.get("/health", summary="Verifica se o processo está ativo")
    async def health():
        return {"status": "ok"}

    @application.get("/ready", summary="Verifica se existe um modelo disponível")
    async def ready():
        predictor = application.state.predictor
        if predictor is None:
            raise HTTPException(status_code=503, detail="Modelo indisponível para inferência.")
        return {
            "status": "pronto",
            "versao_modelo": predictor.version,
            "backend": predictor.backend,
        }

    @application.post(
        "/predict", response_model=PredictionResponse, summary="Classifica um resumo médico"
    )
    def predict(payload: PredictionRequest):
        # A função síncrona é executada pelo FastAPI no pool de threads.
        predictor = application.state.predictor
        if predictor is None:
            raise HTTPException(status_code=503, detail="Modelo indisponível para inferência.")
        try:
            probabilities = _probabilities(predictor, [payload.texto])[0]
            class_ids = sorted(CLASSES)
            class_id = class_ids[int(np.argmax(probabilities))]
            return PredictionResponse(
                classe_id=class_id,
                classe=CLASSES[class_id],
                probabilidades={
                    str(key): float(value)
                    for key, value in zip(class_ids, probabilities, strict=True)
                },
                versao_modelo=predictor.version,
                backend=predictor.backend,
            )
        except Exception:
            # Exceções do modelo podem conter o próprio texto; não são registradas.
            raise HTTPException(
                status_code=500, detail="Não foi possível processar a solicitação."
            ) from None

    @application.get(
        "/metrics", summary="Expõe métricas para o Prometheus", include_in_schema=False
    )
    def prometheus_metrics():
        return Response(
            content=generate_latest(metrics.registry), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

    return application


app = create_app()
