"""Etapas reutilizáveis na linha de comando e no Airflow."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from medical_classifier.benchmark import compare
from medical_classifier.data import download_data, prepare_data, sha256
from medical_classifier.serving import Predictor, resolve_release
from medical_classifier.training import (
    evaluate,
    fit_release,
    promote_release,
    require_latency_gain,
    verified_evaluation,
    write_json,
)


def ingest(raw: Path, prepared: Path) -> str:
    """Verifica o corpus e persiste partições auditadas para a tarefa seguinte."""
    download_data(raw)
    split = prepare_data(raw)
    prepared.mkdir(parents=True, exist_ok=True)
    for name, frame in [
        ("treino", split.train),
        ("validacao", split.validation),
        ("teste", split.test),
    ]:
        frame.to_csv(prepared / f"{name}.csv", index=False)
    split.audit["sha256_preparados"] = {
        name: sha256(prepared / name) for name in ("treino.csv", "validacao.csv", "teste.csv")
    }
    write_json(prepared / "auditoria.json", split.audit)
    return str(prepared)


def verified_audit(prepared: Path) -> dict:
    """Confere que as partições não mudaram entre tarefas de treino e validação."""
    audit = json.loads((prepared / "auditoria.json").read_text("utf-8"))
    for name in ("treino.csv", "validacao.csv", "teste.csv"):
        if sha256(prepared / name) != audit["sha256_preparados"][name]:
            raise ValueError(f"Falha de integridade na partição preparada {name}.")
    return audit


def train(prepared: Path, models: Path) -> str:
    """Ajusta, exporta e valida uma nova versão, sem ativá-la na API."""
    audit = verified_audit(prepared)
    release = fit_release(
        pd.read_csv(prepared / "treino.csv"),
        pd.read_csv(prepared / "validacao.csv"),
        models,
        audit,
    )
    return str(release)


def validate(release: Path, prepared: Path, reports: Path, iterations: int = 400) -> dict:
    """Mede latência na validação e registra teste oficial sem ajustar parâmetros."""
    release = release.resolve()
    models = release.parent.parent
    if (models / "current.json").is_file() and resolve_release(models) == release:
        raise ValueError("A versão já está publicada; valide um novo candidato.")
    metadata = json.loads((release / "metadata.json").read_text("utf-8"))
    evaluation_path = release / "avaliacao.json"
    previous = json.loads(evaluation_path.read_text("utf-8")) if evaluation_path.is_file() else {}
    pending = previous.copy() if isinstance(previous, dict) else {}
    pending.update(
        {
            "aprovado": False,
            "estado": "validação iniciada; resultados anteriores não autorizam publicação",
            "versao_modelo": release.name,
        }
    )
    # Conserva os resultados históricos identificados, mas revoga a aprovação da tentativa.
    write_json(evaluation_path, pending)
    audit = verified_audit(prepared)
    if audit["sha256_preparados"] != metadata["auditoria_dados"]["sha256_preparados"]:
        raise ValueError("As partições de avaliação não correspondem às usadas no treino.")
    original = Predictor.from_release(release, "sklearn")
    optimized = Predictor.from_release(release, "onnx")
    validation = pd.read_csv(prepared / "validacao.csv")
    latency = compare(original, optimized, validation.medical_abstract.tolist(), iterations)
    require_latency_gain(latency)
    if latency.get("versao_modelo") != release.name:
        raise ValueError("O resultado do benchmark não corresponde à versão candidata.")
    test = pd.read_csv(prepared / "teste.csv")
    texts = test.medical_abstract.tolist()
    probabilities = {}
    for name, predictor in [("sklearn", original), ("onnx", optimized)]:
        probabilities[name] = np.concatenate(
            [predictor.predict(texts[i : i + 64]) for i in range(0, len(texts), 64)]
        )
    difference = float(np.max(np.abs(probabilities["sklearn"] - probabilities["onnx"])))
    agreement = float(
        np.mean(probabilities["sklearn"].argmax(1) == probabilities["onnx"].argmax(1))
    )
    if (
        any(not np.isfinite(values).all() for values in probabilities.values())
        or difference > 1e-4
        or agreement != 1.0
    ):
        raise ValueError("Divergência inesperada dos motores no teste oficial.")
    quality = {
        "aprovado": True,
        "estado": "candidato validado; consulte current.json para a versão ativa",
        "sha256_modelos": metadata["sha256"],
        "versao_modelo": original.version,
        "auditoria_dados": metadata["auditoria_dados"],
        "validacao": metadata["validacao"],
        "paridade_validacao": metadata["paridade"],
        "teste": {
            name: evaluate(test.condition_label, values) for name, values in probabilities.items()
        },
        "erro_maximo_probabilidade_teste": difference,
        "concordancia_teste": agreement,
        "tamanho_bytes": {
            name: (release / name).stat().st_size for name in ["baseline.joblib", "model.onnx"]
        },
        "hiperparametros": metadata["hiperparametros"],
        "ambiente": metadata["ambiente"],
    }
    write_json(reports / "qualidade.json", quality)
    write_json(reports / "latencia_modelo.json", latency)
    # A evidência da versão viaja com ela; o teste não decide hiperparâmetros.
    write_json(release / "avaliacao.json", quality)
    write_json(release / "latencia.json", latency)
    return {"qualidade": quality, "latencia": latency}


def execute(
    raw: Path, models: Path, reports: Path, iterations: int = 400, reuse: bool = False
) -> dict:
    """Executa as mesmas etapas da DAG e só então publica a versão validada."""
    if reuse and (models / "current.json").exists():
        release = resolve_release(models)
        for backend in ("sklearn", "onnx"):
            Predictor.from_release(release, backend)
        metadata = json.loads((release / "metadata.json").read_text("utf-8"))
        quality, latency = verified_evaluation(release, metadata)
        write_json(reports / "qualidade.json", quality)
        write_json(reports / "latencia_modelo.json", latency)
        return {"qualidade": quality, "latencia": latency, "reutilizado": True}
    prepared = raw.parent / "prepared"
    ingest(raw, prepared)
    release = Path(train(prepared, models))
    result = validate(release, prepared, reports, iterations)
    promote_release(release, models)
    return result


def main() -> None:
    """Oferece comandos explícitos para reprodução e automação."""
    parser = argparse.ArgumentParser(description="Pipeline de classificação médica")
    parser.add_argument("acao", choices=["executar", "baixar"])
    parser.add_argument("--dados", type=Path, default=Path("data/raw"))
    parser.add_argument("--modelos", type=Path, default=Path("models"))
    parser.add_argument("--relatorios", type=Path, default=Path("reports"))
    parser.add_argument("--iteracoes", type=int, default=400)
    parser.add_argument(
        "--reutilizar",
        action="store_true",
        help="Reutiliza a versão íntegra publicada, sem novo treino no boot.",
    )
    args = parser.parse_args()
    if args.acao == "baixar":
        result = download_data(args.dados)
    else:
        result = execute(args.dados, args.modelos, args.relatorios, args.iteracoes, args.reutilizar)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
