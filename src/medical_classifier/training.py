"""Treinamento, exportação ONNX e publicação após gates de qualidade."""

import json
import os
import platform
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import joblib
import numpy as np
import onnx
import onnxruntime as ort
import pandas as pd
import skl2onnx
import sklearn
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import StringTensorType
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline
from threadpoolctl import threadpool_limits

from medical_classifier.data import CLASSES, normalize, sha256


def write_json(path: Path, value: dict) -> None:
    """Grava JSON legível em português e sem valores não finitos."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), "utf-8")


def evaluate(labels, probabilities: np.ndarray) -> dict:
    """Resume qualidade por classe sem alterar o modelo avaliado."""
    predictions = np.asarray(list(CLASSES))[probabilities.argmax(axis=1)]
    return {
        "acuracia": float(accuracy_score(labels, predictions)),
        "f1_macro": float(f1_score(labels, predictions, average="macro")),
        "matriz_confusao": confusion_matrix(labels, predictions, labels=list(CLASSES)).tolist(),
        "por_classe": classification_report(
            labels,
            predictions,
            labels=list(CLASSES),
            target_names=list(CLASSES.values()),
            output_dict=True,
            zero_division=0,
        ),
    }


def fit_release(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    model_root: Path,
    audit: dict,
    min_macro_f1: float = 0.55,
) -> Path:
    """Treina só na partição de ajuste e verifica qualidade/paridade na validação."""
    version = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    release = model_root / "releases" / version
    release.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".treino-", dir=model_root) as temporary:
        candidate = Path(temporary) / version
        candidate.mkdir()
        _fit_bundle(train, validation, candidate, audit, min_macro_f1)
        candidate.replace(release)
    return release


def _fit_bundle(train, validation, release: Path, audit: dict, min_macro_f1: float) -> None:
    """Grava o conjunto candidato; o chamador só o publica se todos os gates passarem."""
    model = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=False,
                    token_pattern=r"[a-zA-Z]{2,}",
                    max_features=20000,
                    ngram_range=(1, 2),
                    # O conversor 1.19 aplica log(1+tf) para o modo sublinear.
                    # TF linear preserva a fórmula do scikit-learn no grafo ONNX.
                    sublinear_tf=False,
                    dtype=np.float32,
                ),
            ),
            ("classifier", LogisticRegression(C=4.0, max_iter=500, class_weight="balanced")),
        ]
    )
    with threadpool_limits(limits=1):
        model.fit(train.medical_abstract.map(normalize), train.condition_label)
    classifier = model.named_steps["classifier"]
    if np.max(classifier.n_iter_) >= classifier.max_iter:
        raise ValueError("O treinamento atingiu o limite de iterações sem convergir.")
    if list(model.classes_) != list(CLASSES):
        raise ValueError("O treinamento não produziu as cinco classes esperadas.")
    texts = validation.medical_abstract.map(normalize).tolist()
    original = model.predict_proba(texts)
    metrics = evaluate(validation.condition_label, original)
    if metrics["f1_macro"] < min_macro_f1:
        raise ValueError("Modelo reprovado no piso de F1 macro da validação.")
    joblib.dump(model, release / "baseline.joblib")
    converted = convert_sklearn(
        model,
        initial_types=[("texto", StringTensorType([None, 1]))],
        options={id(model.named_steps["classifier"]): {"zipmap": False}},
        target_opset=17,
    )
    (release / "model.onnx").write_bytes(converted.SerializeToString())
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    session = ort.InferenceSession(
        str(release / "model.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
    )
    # Lotes limitados evitam uma matriz densa de todo o corpus na exportação.
    optimized = np.concatenate(
        [
            session.run(None, {"texto": np.array(texts[i : i + 64], dtype=object).reshape(-1, 1)})[
                1
            ]
            for i in range(0, len(texts), 64)
        ]
    )
    difference = float(np.max(np.abs(original - optimized)))
    agreement = float(np.mean(original.argmax(1) == optimized.argmax(1)))
    if not np.isfinite(optimized).all() or difference > 1e-4 or agreement != 1.0:
        raise ValueError(
            "Conversão ONNX reprovada no gate de paridade: "
            f"erro_maximo_probabilidade={difference:.9g}; concordancia={agreement:.9g}; "
            f"valores_nao_finitos={int((~np.isfinite(optimized)).sum())}; "
            f"amostras={len(texts)}."
        )
    metadata = {
        "versao": release.name,
        "classes": list(CLASSES),
        "nomes_classes": CLASSES,
        "criado_em": datetime.now(UTC).isoformat(),
        "auditoria_dados": audit,
        "validacao": metrics,
        "piso_f1_macro": min_macro_f1,
        "paridade": {"erro_maximo_probabilidade": difference, "concordancia": agreement},
        "sha256": {name: sha256(release / name) for name in ["baseline.joblib", "model.onnx"]},
        "ambiente": {
            "python": platform.python_version(),
            "sklearn": sklearn.__version__,
            "onnxruntime": ort.__version__,
            "onnx": onnx.__version__,
            "skl2onnx": skl2onnx.__version__,
        },
        "hiperparametros": {
            "tfidf": {
                key: str(value) if isinstance(value, type) else value
                for key, value in model.named_steps["tfidf"].get_params().items()
            },
            "regressao_logistica": classifier.get_params(),
        },
        "iteracoes_solver": classifier.n_iter_.tolist(),
        "aprovado": True,
    }
    write_json(release / "metadata.json", metadata)


def promote_release(release: Path, model_root: Path) -> None:
    """Atualiza um ponteiro atomicamente sem sobrescrever a versão em uso."""
    root = model_root.resolve()
    release = release.resolve()
    if not release.is_relative_to(root / "releases"):
        raise ValueError("Versão fora do diretório dos modelos.")
    metadata = json.loads((release / "metadata.json").read_text("utf-8"))
    if not metadata.get("aprovado"):
        raise ValueError("Modelo sem aprovação dos gates.")
    for name in ("baseline.joblib", "model.onnx"):
        if sha256(release / name) != metadata["sha256"][name]:
            raise ValueError("Falha de integridade antes da publicação.")
    previous = None
    if (root / "current.json").exists():
        from medical_classifier.serving import resolve_release

        previous_release = resolve_release(root)
        if previous_release == release:
            return
        previous = previous_release.relative_to(root).as_posix()
        old = json.loads((previous_release / "metadata.json").read_text("utf-8"))
        new_hash = metadata["auditoria_dados"].get("sha256_preparados", {}).get("validacao.csv")
        old_hash = old["auditoria_dados"].get("sha256_preparados", {}).get("validacao.csv")
        if new_hash and new_hash == old_hash:
            if metadata["validacao"]["f1_macro"] + 1e-6 < old["validacao"]["f1_macro"]:
                raise ValueError("Publicação bloqueada por regressão de F1 na mesma validação.")
    temp = root / f".current-{uuid.uuid4().hex}.json"
    write_json(temp, {"release": release.relative_to(root).as_posix(), "anterior": previous})
    os.replace(temp, root / "current.json")
