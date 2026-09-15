"""Verifica a reutilização de versões publicadas sem retreino no boot."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from medical_classifier import pipeline
from medical_classifier.data import sha256
from medical_classifier.training import fit_release, promote_release, write_json
from tests.test_data import corpus


def preparar_candidato(tmp_path):
    """Gera partições auditadas e um candidato sintético sem simular as probabilidades."""
    frame = corpus(10)
    names = ["treino.csv", "validacao.csv", "teste.csv"]
    for name in names:
        frame.to_csv(tmp_path / name, index=False)
    audit = {"sha256_preparados": {name: sha256(tmp_path / name) for name in names}}
    write_json(tmp_path / "auditoria.json", audit)
    return fit_release(frame, frame, tmp_path / "models", audit, min_macro_f1=0)


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
    write_json(release / "avaliacao.json", result["qualidade"])
    write_json(
        release / "latencia.json", {"fator_aceleracao_p50": 0.8, "versao_modelo": release.name}
    )
    with pytest.raises(ValueError, match="ganho de latência"):
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
    assert json.loads((release / "avaliacao.json").read_text("utf-8"))["aprovado"] is False
    with pytest.raises(ValueError, match="relatórios de avaliação completos"):
        promote_release(release, tmp_path / "models")
    assert not (tmp_path / "models" / "current.json").exists()


def test_validacao_rejeita_troca_de_classe_mesmo_com_erro_numerico_pequeno(tmp_path, monkeypatch):
    """O teste oficial deve manter a classe inclusive quando as duas maiores saídas empatam."""
    frame = corpus(10)
    names = ["treino.csv", "validacao.csv", "teste.csv"]
    for name in names:
        frame.to_csv(tmp_path / name, index=False)
    audit = {"sha256_preparados": {name: sha256(tmp_path / name) for name in names}}
    write_json(tmp_path / "auditoria.json", audit)
    release = fit_release(frame, frame, tmp_path / "models", audit, min_macro_f1=0)
    probabilidades = {
        "sklearn": np.array([0.35001, 0.34999, 0.1, 0.1, 0.1]),
        "onnx": np.array([0.34999, 0.35001, 0.1, 0.1, 0.1]),
    }

    def predictor_controlado(release, backend):
        return SimpleNamespace(
            version=release.name,
            predict=lambda textos: np.tile(probabilidades[backend], (len(textos), 1)),
        )

    monkeypatch.setattr(pipeline.Predictor, "from_release", predictor_controlado)
    monkeypatch.setattr(
        pipeline,
        "compare",
        lambda *args: {"fator_aceleracao_p50": 2.0, "versao_modelo": release.name},
    )
    with pytest.raises(ValueError, match="Divergência inesperada"):
        pipeline.validate(release, tmp_path, tmp_path / "reports")
    assert json.loads((release / "avaliacao.json").read_text("utf-8"))["aprovado"] is False


@pytest.mark.parametrize("versao_benchmark", [None, "outra-versao"])
def test_validacao_rejeita_benchmark_sem_vinculo_da_versao(tmp_path, monkeypatch, versao_benchmark):
    release = preparar_candidato(tmp_path)
    latencia = {"fator_aceleracao_p50": 2.0}
    if versao_benchmark is not None:
        latencia["versao_modelo"] = versao_benchmark
    monkeypatch.setattr(pipeline, "compare", lambda *args: latencia)
    with pytest.raises(ValueError, match="benchmark.*versão candidata"):
        pipeline.validate(release, tmp_path, tmp_path / "reports")
    assert not (release / "latencia.json").exists()
    assert not (tmp_path / "reports" / "qualidade.json").exists()


def test_revalidacao_reprovada_invalida_aprovacao_anterior(tmp_path, monkeypatch):
    release = preparar_candidato(tmp_path)
    latencia = {"fator_aceleracao_p50": 2.0, "versao_modelo": release.name}
    monkeypatch.setattr(pipeline, "compare", lambda *args: latencia.copy())
    resultado = pipeline.validate(release, tmp_path, tmp_path / "reports")
    assert resultado["qualidade"]["aprovado"] is True
    artefatos = ["baseline.joblib", "model.onnx", "metadata.json"]
    hashes_anteriores = {nome: sha256(release / nome) for nome in artefatos}
    latencia_anterior = (release / "latencia.json").read_bytes()

    latencia["fator_aceleracao_p50"] = 0.8
    with pytest.raises(ValueError, match="ganho de latência"):
        pipeline.validate(release, tmp_path, tmp_path / "reports")
    with pytest.raises(ValueError, match="avaliação aprovada"):
        promote_release(release, tmp_path / "models")

    avaliacao = json.loads((release / "avaliacao.json").read_text("utf-8"))
    assert avaliacao["aprovado"] is False
    assert "anteriores" in avaliacao["estado"]
    assert avaliacao["teste"] == resultado["qualidade"]["teste"]
    assert (release / "latencia.json").read_bytes() == latencia_anterior
    assert {nome: sha256(release / nome) for nome in artefatos} == hashes_anteriores
    assert not (tmp_path / "models" / "current.json").exists()

    latencia["fator_aceleracao_p50"] = 2.0
    pipeline.validate(release, tmp_path, tmp_path / "reports")
    promote_release(release, tmp_path / "models")
    assert json.loads((tmp_path / "models" / "current.json").read_text("utf-8"))[
        "release"
    ].endswith(release.name)


def test_validacao_preserva_versao_atualmente_publicada(tmp_path, monkeypatch):
    release = preparar_candidato(tmp_path)
    latencia = {"fator_aceleracao_p50": 2.0, "versao_modelo": release.name}
    monkeypatch.setattr(pipeline, "compare", lambda *args: latencia.copy())
    pipeline.validate(release, tmp_path, tmp_path / "reports")
    promote_release(release, tmp_path / "models")
    caminhos = [release / nome for nome in ("avaliacao.json", "latencia.json", "metadata.json")]
    caminhos.append(tmp_path / "models" / "current.json")
    estado_anterior = {caminho: caminho.read_bytes() for caminho in caminhos}
    latencia["fator_aceleracao_p50"] = 0.8

    with pytest.raises(ValueError, match="já está publicada.*novo candidato"):
        pipeline.validate(release, tmp_path, tmp_path / "reports")

    assert {caminho: caminho.read_bytes() for caminho in caminhos} == estado_anterior
