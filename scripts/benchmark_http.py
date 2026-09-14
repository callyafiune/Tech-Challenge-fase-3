"""Mede a latência HTTP pareada das APIs original e otimizada."""

import argparse
import platform
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

import httpx
import numpy as np
import pandas as pd

from medical_classifier.benchmark import summarize
from medical_classifier.training import write_json


def measure(
    urls: dict[str, str], texts: list[str], iterations: int, warmup: int, environment: str
) -> dict:
    """Confere motores/versão e reutiliza conexões durante amostras alternadas."""
    durations = {name: [] for name in urls}
    with httpx.Client(timeout=30, trust_env=False) as client:
        readiness = {}
        for name, url in urls.items():
            response = client.get(f"{url}/ready")
            response.raise_for_status()
            readiness[name] = response.json()
            if readiness[name]["backend"] != name:
                raise ValueError(f"Motor inesperado no endpoint {name}.")
        if len({value["versao_modelo"] for value in readiness.values()}) != 1:
            raise ValueError("Os endpoints devem carregar a mesma versão do modelo.")
        rng = np.random.default_rng(42)
        for i in range(warmup + iterations):
            text = texts[int(rng.integers(len(texts)))]
            names = ["sklearn", "onnx"] if i % 2 == 0 else ["onnx", "sklearn"]
            predictions = []
            for name in names:
                start = perf_counter_ns()
                response = client.post(f"{urls[name]}/predict", json={"texto": text})
                elapsed = (perf_counter_ns() - start) / 1e6
                response.raise_for_status()
                body = response.json()
                if body["versao_modelo"] != readiness[name]["versao_modelo"]:
                    raise ValueError("A versão mudou durante a medição.")
                predictions.append(body["classe_id"])
                if i >= warmup:
                    durations[name].append(elapsed)
            if len(set(predictions)) != 1:
                raise ValueError("Os motores divergiram na classificação HTTP.")
    result = {name: summarize(values) for name, values in durations.items()}
    result.update(
        {
            "fator_aceleracao_p50": result["sklearn"]["p50_ms"] / result["onnx"]["p50_ms"],
            "fator_aceleracao_p95": result["sklearn"]["p95_ms"] / result["onnx"]["p95_ms"],
            "metodo": "HTTP local, lote 1, concorrência 1, conexões persistentes e ordem alternada",
            "ambiente_servidores": environment,
            "endpoints": urls,
            "ambiente_cliente": {
                "plataforma": platform.platform(),
                "processador": platform.processor(),
                "python": platform.python_version(),
            },
            "semente": 42,
            "aquecimento_por_motor": warmup,
            "prontidao": readiness,
            "instante_utc": datetime.now(UTC).isoformat(),
        }
    )
    return result


def main() -> None:
    """Recebe endpoints e dados de validação sem misturar o conjunto de teste."""
    parser = argparse.ArgumentParser(description="Compara a latência HTTP dos dois motores")
    parser.add_argument("--original", default="http://localhost:8001")
    parser.add_argument("--otimizado", default="http://localhost:8000")
    parser.add_argument("--dados", type=Path, default=Path("data/prepared/validacao.csv"))
    parser.add_argument("--saida", type=Path, default=Path("reports/latencia_http.json"))
    parser.add_argument("--iteracoes", type=int, default=200)
    parser.add_argument("--aquecimento", type=int, default=20)
    parser.add_argument(
        "--ambiente",
        required=True,
        choices=["host", "docker"],
        help="Identifica onde os dois servidores estão executando.",
    )
    args = parser.parse_args()
    if args.iteracoes < 2 or args.aquecimento < 1:
        parser.error("Use pelo menos duas iterações e um aquecimento.")
    texts = pd.read_csv(args.dados).medical_abstract.tolist()
    if not texts:
        parser.error("Os dados não contêm textos.")
    result = measure(
        {"sklearn": args.original, "onnx": args.otimizado},
        texts,
        args.iteracoes,
        args.aquecimento,
        args.ambiente,
    )
    write_json(args.saida, result)
    print(f"Comparação gravada em {args.saida}")


if __name__ == "__main__":
    main()
