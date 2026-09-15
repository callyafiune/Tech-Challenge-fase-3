"""Reexporta um baseline existente e compara os grafos sem treinar ou publicar."""

from __future__ import annotations

import argparse
import json
import platform
from copy import deepcopy
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
import onnxruntime as ort
import pandas as pd
from threadpoolctl import threadpool_limits

from medical_classifier.data import normalize, sha256
from medical_classifier.training import export_onnx


def comparar(referencia: np.ndarray, observado: np.ndarray) -> dict:
    """Rejeita saída inválida e resume a paridade sem copiar os resumos médicos."""
    if observado.shape != referencia.shape or not np.isfinite(observado).all():
        raise ValueError("A inferência retornou probabilidades inválidas.")
    erro = np.abs(referencia - observado)
    return {
        "erro_maximo": float(erro.max()),
        "concordancia": float(np.mean(referencia.argmax(1) == observado.argmax(1))),
        "linhas_divergentes": int(np.any(erro > 1e-4, axis=1).sum()),
    }


def verificar(baseline: Path, anterior: Path, dados: Path) -> dict:
    """Compara validação e teste no mesmo ajuste, preservando arquivos e estado."""
    hashes = {"baseline": sha256(baseline), "onnx_anterior": sha256(anterior)}
    modelo = joblib.load(baseline)
    estado = joblib.hash(modelo)
    # A inferência atualiza caches internos do scikit-learn; isole essa referência.
    modelo_referencia = deepcopy(modelo)
    opcoes = ort.SessionOptions()
    opcoes.intra_op_num_threads = 1
    opcoes.inter_op_num_threads = 1
    sessoes = {
        "antes": ort.InferenceSession(
            str(anterior), sess_options=opcoes, providers=["CPUExecutionProvider"]
        ),
        "depois": ort.InferenceSession(
            export_onnx(modelo).SerializeToString(),
            sess_options=opcoes,
            providers=["CPUExecutionProvider"],
        ),
    }
    relatorio = {
        "verificado_em": datetime.now(UTC).isoformat(),
        "reajuste_executado": False,
        "publicacao_executada": False,
        "conversao": "medical_classifier.training.export_onnx",
        "entradas_sha256": hashes,
        "ambiente": {
            "python": platform.python_version(),
            "sistema": platform.system(),
            **{nome: version(nome) for nome in ("scikit-learn", "skl2onnx", "onnxruntime")},
        },
    }
    aprovado = True
    for nome in ("validacao", "teste"):
        arquivo = dados / f"{nome}.csv"
        frame = pd.read_csv(arquivo)
        if frame.empty or frame["medical_abstract"].isna().any():
            raise ValueError("A partição deve conter resumos não vazios.")
        textos = [normalize(texto) for texto in frame["medical_abstract"]]
        referencia = modelo_referencia.predict_proba(textos)
        medidas = {"amostras": len(textos), "dados_sha256": sha256(arquivo)}
        for motor, sessao in sessoes.items():
            entrada = sessao.get_inputs()[0].name
            lotes = [
                sessao.run(
                    None, {entrada: np.array(textos[i : i + 64], dtype=object).reshape(-1, 1)}
                )[1]
                for i in range(0, len(textos), 64)
            ]
            medidas[motor] = comparar(referencia, np.concatenate(lotes))
        aprovado = aprovado and (
            medidas["depois"]["erro_maximo"] <= 1e-4 and medidas["depois"]["concordancia"] == 1.0
        )
        relatorio[nome] = medidas
    preservado = (
        joblib.hash(modelo) == estado
        and sha256(baseline) == hashes["baseline"]
        and sha256(anterior) == hashes["onnx_anterior"]
    )
    relatorio["modelo_sklearn_e_arquivos_preservados"] = preservado
    relatorio["sucesso"] = bool(aprovado and preservado)
    return relatorio


def main() -> int:
    """Exige caminhos explícitos e grava um relatório novo, sem sobrescrever fontes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="Baseline joblib confiável.")
    parser.add_argument("--onnx-anterior", type=Path, required=True, help="Grafo a comparar.")
    parser.add_argument("--dados", type=Path, required=True, help="Diretório dos CSVs preparados.")
    parser.add_argument("--saida", type=Path, required=True, help="Novo arquivo JSON de evidência.")
    args = parser.parse_args()
    if args.saida.exists():
        raise FileExistsError("Use um arquivo de saída novo para preservar as evidências.")
    with threadpool_limits(limits=1):
        relatorio = verificar(args.baseline, args.onnx_anterior, args.dados)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    with args.saida.open("x", encoding="utf-8") as arquivo:
        json.dump(relatorio, arquivo, ensure_ascii=False, indent=2, allow_nan=False)
        arquivo.write("\n")
    print(json.dumps({"sucesso": relatorio["sucesso"], "relatorio": str(args.saida)}))
    return 0 if relatorio["sucesso"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
