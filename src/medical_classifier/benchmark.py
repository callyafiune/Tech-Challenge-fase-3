"""Comparação pareada de latência, incluindo normalização e vetorização."""

import platform
from time import perf_counter_ns

import numpy as np
from threadpoolctl import threadpool_limits


def summarize(values: list[float]) -> dict:
    """Calcula percentis em milissegundos e volume efetivamente medido."""
    return {
        "amostras": len(values),
        "media_ms": float(np.mean(values)),
        "p50_ms": float(np.percentile(values, 50)),
        "p95_ms": float(np.percentile(values, 95)),
        "p99_ms": float(np.percentile(values, 99)),
    }


def compare(original, optimized, texts: list[str], iterations: int = 400, warmup: int = 30) -> dict:
    """Alterna a ordem dos motores para reduzir viés de aquecimento e deriva temporal."""
    if not texts or iterations < 2 or warmup < 1:
        raise ValueError("Informe textos, ao menos duas iterações e aquecimento positivo.")
    rng = np.random.default_rng(42)
    sample = [texts[i] for i in rng.integers(0, len(texts), size=iterations)]
    durations = {"sklearn": [], "onnx": []}
    engines = {"sklearn": original, "onnx": optimized}
    with threadpool_limits(limits=1):
        for i in range(warmup):
            for predictor in engines.values():
                predictor.predict([sample[i % iterations]])
        for i, text in enumerate(sample):
            order = ["sklearn", "onnx"] if i % 2 == 0 else ["onnx", "sklearn"]
            for name in order:
                start = perf_counter_ns()
                engines[name].predict([text])
                durations[name].append((perf_counter_ns() - start) / 1e6)
    report = {name: summarize(values) for name, values in durations.items()}
    report.update(
        {
            "fator_aceleracao_p50": report["sklearn"]["p50_ms"] / report["onnx"]["p50_ms"],
            "fator_aceleracao_p95": report["sklearn"]["p95_ms"] / report["onnx"]["p95_ms"],
            "metodo": "Inferência completa, lote 1, ordem alternada, mesmos textos, sem HTTP",
            "aquecimento_por_motor": warmup,
            "semente": 42,
            "threads_nativas": 1,
            "plataforma": platform.platform(),
            "processador": platform.processor(),
            "versao_modelo": original.version,
        }
    )
    return report
