"""Carregamento íntegro de uma versão imutável e inferência comum aos dois motores."""

import json
from pathlib import Path

import joblib
import numpy as np
import onnxruntime as ort

from medical_classifier.data import CLASSES, normalize, sha256


def resolve_release(model_dir: Path) -> Path:
    """Resolve o ponteiro sem permitir escapar do diretório dos modelos."""
    root = model_dir.resolve()
    pointer = json.loads((root / "current.json").read_text("utf-8"))
    release = (root / pointer["release"]).resolve()
    if not release.is_relative_to(root / "releases"):
        raise ValueError("Versão fora do diretório permitido.")
    return release


class Predictor:
    """Mantém um único modelo em memória, sem fallback silencioso de motor."""

    def __init__(self, model_dir: Path, backend: str = "onnx") -> None:
        self._load(resolve_release(Path(model_dir)), backend)

    @classmethod
    def from_release(cls, release: Path, backend: str = "onnx") -> "Predictor":
        """Carrega uma versão candidata para validação antes de publicar o ponteiro."""
        predictor = cls.__new__(cls)
        predictor._load(release, backend)
        return predictor

    def _load(self, release: Path, backend: str) -> None:
        if backend not in {"onnx", "sklearn"}:
            raise ValueError("Motor inválido; use onnx ou sklearn.")
        metadata = json.loads((release / "metadata.json").read_text("utf-8"))
        filename = "model.onnx" if backend == "onnx" else "baseline.joblib"
        if sha256(release / filename) != metadata["sha256"][filename]:
            raise ValueError("Falha de integridade do modelo.")
        if metadata["classes"] != sorted(CLASSES):
            raise ValueError("Ordem de classes incompatível com a API.")
        if metadata.get("aprovado") is not True:
            raise ValueError("O modelo não passou pelos gates de aprovação.")
        self.classes = metadata["classes"]
        self.backend = backend
        self.version = metadata["versao"]
        if backend == "onnx":
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            self.model = ort.InferenceSession(
                str(release / filename), sess_options=options, providers=["CPUExecutionProvider"]
            )
        else:
            self.model = joblib.load(release / filename)

    def predict(self, texts: list[str]) -> np.ndarray:
        """Retorna probabilidades nas cinco classes, na ordem dos ids 1 a 5."""
        normalized = [normalize(text) for text in texts]
        if self.backend == "sklearn":
            return self.model.predict_proba(normalized)
        outputs = self.model.run(None, {"texto": np.array(normalized, dtype=object).reshape(-1, 1)})
        return np.asarray(outputs[1])
