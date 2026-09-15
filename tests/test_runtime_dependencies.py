"""Verifica a API ONNX em processos sem acesso às bibliotecas de treinamento."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def modelo_publicado(tmp_path):
    """Prepara um artefato real antes de isolar as dependências do processo de inferência."""
    import pandas as pd

    from medical_classifier.training import fit_release, promote_release, write_json

    palavras = ["tumor cancer", "stomach bowel", "brain nerve", "heart artery", "fever pain"]
    frame = pd.DataFrame(
        [
            {"condition_label": classe + 1, "medical_abstract": f"clinical study {palavra} " * n}
            for classe, palavra in enumerate(palavras)
            for n in range(1, 5)
        ]
    )
    release = fit_release(frame, frame, tmp_path, {"origem": "teste sintético"})
    metadata = json.loads((release / "metadata.json").read_text("utf-8"))
    # As evidências sintéticas autorizam apenas a publicação desta fixture de integração.
    write_json(
        release / "avaliacao.json",
        {"aprovado": True, "versao_modelo": release.name, "sha256_modelos": metadata["sha256"]},
    )
    write_json(
        release / "latencia.json", {"fator_aceleracao_p50": 2.0, "versao_modelo": release.name}
    )
    promote_release(release, tmp_path)
    return tmp_path, release


def executar_processo_isolado(tmp_path, bloqueados, codigo):
    """Bloqueia imports em um interpretador novo, mesmo com o ambiente dev completo instalado."""
    fonte = Path(__file__).resolve().parents[1] / "src"
    preambulo = f"""
import importlib.abc
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, {str(fonte)!r})
bloqueados = {bloqueados!r}

class BloquearTreinamento(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in bloqueados:
            raise ModuleNotFoundError("Dependência ausente neste teste: " + fullname, name=fullname)
        return None

assert not any(nome.split(".", 1)[0] in bloqueados for nome in sys.modules)
sys.meta_path.insert(0, BloquearTreinamento())
"""
    programa = tmp_path / "inferir_sem_treinamento.py"
    programa.write_text(preambulo + "\n" + textwrap.dedent(codigo), encoding="utf-8")
    resultado = subprocess.run(
        [sys.executable, "-I", str(programa)],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


def test_api_onnx_inicia_e_classifica_sem_dependencias_de_treinamento(tmp_path, modelo_publicado):
    modelos, release = modelo_publicado
    executar_processo_isolado(
        tmp_path,
        {
            "pandas",
            "sklearn",
            "scipy",
            "joblib",
            "onnx",
            "skl2onnx",
            "threadpoolctl",
            "ml_dtypes",
            "dateutil",
            "pytz",
            "six",
            "tzdata",
        },
        f"""
        from fastapi.testclient import TestClient
        from medical_classifier.api import create_app

        with TestClient(create_app(model_dir=Path({str(modelos)!r}), backend="onnx")) as cliente:
            assert cliente.get("/health").status_code == 200
            prontidao = cliente.get("/ready")
            assert prontidao.status_code == 200
            assert prontidao.json()["versao_modelo"] == {release.name!r}
            resposta = cliente.post(
                "/predict", json={{"texto": "clinical study heart artery treatment"}}
            )
            assert resposta.status_code == 200
            assert resposta.json()["classe_id"] == 4
            assert resposta.json()["backend"] == "onnx"
            assert "http_requests_total" in cliente.get("/metrics").text
        assert not any(nome.split(".", 1)[0] in bloqueados for nome in sys.modules)
        """,
    )


@pytest.mark.parametrize("dependencia_ausente", ["joblib", "sklearn"])
def test_backend_sklearn_informa_dependencia_opcional_ausente(
    tmp_path, modelo_publicado, dependencia_ausente
):
    _, release = modelo_publicado
    executar_processo_isolado(
        tmp_path,
        {dependencia_ausente},
        f"""
        from medical_classifier.serving import Predictor

        try:
            Predictor.from_release(Path({str(release)!r}), "sklearn")
        except RuntimeError as erro:
            assert "dependências de treinamento" in str(erro)
            assert "[treinamento]" in str(erro)
        else:
            raise AssertionError("O backend sklearn não pode iniciar sem suas dependências.")
        """,
    )
