"""Instrumentação HTTP com cardinalidade limitada e registro isolado por aplicação."""

from __future__ import annotations

from time import perf_counter

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Info
from starlette._utils import get_route_path
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class HttpMetrics:
    """Agrupa as métricas de uma única instância da API."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "http_requests_total",
            "Quantidade de requisições HTTP, incluindo respostas de erro.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "http_request_duration_seconds",
            "Duração das requisições HTTP em segundos.",
            ("method", "route"),
            registry=self.registry,
        )
        self.model_ready = Gauge(
            "model_ready",
            "Indica se o modelo está carregado e disponível para inferência.",
            registry=self.registry,
        )
        self.model_info = Info(
            "model",
            "Identificação da versão aquecida e do motor de inferência.",
            ("versao", "backend"),
            registry=self.registry,
        )


class HttpMetricsMiddleware:
    """Observa a resposta ASGI, inclusive quando uma exceção interrompe a rota."""

    METHODS = frozenset(
        {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
    )

    def __init__(self, app: ASGIApp, metrics: HttpMetrics, routes: list[BaseRoute]) -> None:
        self.app = app
        self.metrics = metrics
        self.routes = routes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or get_route_path(scope) in {"/metrics", "/metrics/"}:
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        status = 500

        async def observe_response(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observe_response)
        finally:
            if scope.get("medical_client_disconnected"):
                status = 499
            method = scope["method"] if scope["method"] in self.METHODS else "OUTRO"
            # Somente moldes e caminhos registrados são admitidos como rótulos.
            route = getattr(scope.get("route"), "path", None)
            if route is None:
                path = get_route_path(scope)
                known = any(getattr(item, "path", None) == path for item in self.routes)
                route = path if known else "/outra"
            self.metrics.requests.labels(method, route, str(status)).inc()
            self.metrics.duration.labels(method, route).observe(perf_counter() - started)
