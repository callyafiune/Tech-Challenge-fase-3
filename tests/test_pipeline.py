"""Verifica a reutilização de versões publicadas sem retreino no boot."""

import json

import pytest

from medical_classifier import pipeline
from medical_classifier.data import sha256
from medical_classifier.training import fit_release, promote_release, write_json
from tests.test_data import corpus


def test_reutiliza_modelo_integro_sem_acessar_dados(tmp_path, monkeypatch):
    models = tmp_path / "models"
    frame = corpus(10)
    release = fit_release(frame, frame, models, {}, min_macro_f1=0)
    metadata = json.loads((release / "metadata.json").read_text("utf-8"))
    write_json(
        release / "avaliacao.json",
        {"aprovado": True, "versao_modelo": release.name, "sha256_modelos": metadata["sha256"]},
    )
    write_json(
        release / "latencia.json", {"fator_aceleracao_p50": 2.0, "versao_modelo": release.name}
    )
    promote_release(release, models)

    def prohibit(*args):
        pytest.fail("A reutilização não deve executar ingestão nem acessar a rede.")

    monkeypatch.setattr(pipeline, "ingest", prohibit)
    result = pipeline.execute(tmp_path / "sem_dados", models, tmp_path / "reports", reuse=True)
    assert result["reutilizado"] is True
    assert result["qualidade"]["aprovado"] is True
    assert json.loads((tmp_path / "reports" / "qualidade.json").read_text())["aprovado"]
    write_json(release / "avaliacao.json", {"aprovado": True, "versao_modelo": "outra"})
    with pytest.raises(ValueError, match="não correspondem"):
        pipeline.execute(tmp_path / "sem_dados", models, tmp_path / "reports", reuse=True)


def test_reutilizacao_rejeita_artefato_invalido(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "current.json").write_text('{"release":"../fora"}')
    with pytest.raises(ValueError, match="diretório"):
        pipeline.execute(tmp_path / "dados", models, tmp_path / "reports", reuse=True)


def test_treino_rejeita_particao_alterada(tmp_path):
    frame = corpus(10)
    names = ["treino.csv", "validacao.csv", "teste.csv"]
    for name in names:
        frame.to_csv(tmp_path / name, index=False)
    write_json(
        tmp_path / "auditoria.json",
        {"sha256_preparados": {name: sha256(tmp_path / name) for name in names}},
    )
    (tmp_path / "treino.csv").write_text("alterado")
    with pytest.raises(ValueError, match="integridade"):
        pipeline.train(tmp_path, tmp_path / "models")


def test_validacao_bloqueia_onnx_mais_lento(tmp_path, monkeypatch):
    frame = corpus(10)
    names = ["treino.csv", "validacao.csv", "teste.csv"]
    for name in names:
        frame.to_csv(tmp_path / name, index=False)
    audit = {"sha256_preparados": {name: sha256(tmp_path / name) for name in names}}
    write_json(tmp_path / "auditoria.json", audit)
    release = fit_release(frame, frame, tmp_path / "models", audit, min_macro_f1=0)
    monkeypatch.setattr(pipeline, "compare", lambda *args: {"fator_aceleracao_p50": 0.8})
    with pytest.raises(ValueError, match="ganho de latência"):
        pipeline.validate(release, tmp_path, tmp_path / "reports")
    assert not (release / "avaliacao.json").exists()
