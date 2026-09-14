"""Testes de integração entre treinamento, exportação e carregamento."""

import json
from functools import partial

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from medical_classifier import training
from medical_classifier.serving import Predictor
from medical_classifier.training import export_onnx, fit_release, promote_release
from tests.test_data import corpus


def test_exportacao_preserva_bigrama_sem_unigrama_no_vocabulario(tmp_path, monkeypatch):
    """O corte do vocabulário pode preservar o bigrama e remover uma de suas palavras."""
    vocabulario = {
        "gadopentetate": 0,
        "gadopentetate dimeglumine": 1,
        "bowel": 2,
        "nerve": 3,
        "artery": 4,
        "fever": 5,
        "bowel nerve": 6,
    }
    monkeypatch.setattr(
        training, "TfidfVectorizer", partial(TfidfVectorizer, vocabulary=vocabulario)
    )
    palavras = ["gadopentetate dimeglumine", "bowel nerve", "nerve", "artery", "fever"]
    frame = pd.DataFrame(
        [
            {"condition_label": classe + 1, "medical_abstract": (palavra + " ") * repeticoes}
            for classe, palavra in enumerate(palavras)
            for repeticoes in range(1, 5)
        ]
    )
    release = fit_release(frame, frame, tmp_path, {})
    original = Predictor.from_release(release, "sklearn")
    otimizado = Predictor.from_release(release, "onnx")
    textos = ["gadopentetate dimeglumine", "gadopentetate", "gadopentetate dimeglumine fever"]
    np.testing.assert_allclose(original.predict(textos), otimizado.predict(textos), atol=1e-5)


def test_exportacao_nao_modifica_vocabulario_idf_coeficientes_ou_predicoes(tmp_path):
    frame = corpus(10)
    release = fit_release(frame, frame, tmp_path, {}, min_macro_f1=0)
    modelo = joblib.load(release / "baseline.joblib")
    textos = ["cancer tumor", "clinical study", "brain nerve"]
    probabilidades = modelo.predict_proba(textos)
    estado_anterior = joblib.hash(modelo)

    export_onnx(modelo)

    assert joblib.hash(modelo) == estado_anterior
    assert all(isinstance(termo, str) for termo in modelo.named_steps["tfidf"].vocabulary_)
    np.testing.assert_array_equal(modelo.predict_proba(textos), probabilidades)


def test_paridade_com_frequencias_de_palavras_distintas(tmp_path):
    palavras = ["tumor cancer", "stomach bowel", "brain nerve", "heart artery", "fever pain"]
    frame = pd.DataFrame(
        [
            {
                "condition_label": i + 1,
                "medical_abstract": f"clinical study patient {palavra} " + (palavra + " ") * n,
            }
            for i, palavra in enumerate(palavras)
            for n in range(1, 7)
        ]
    )
    release = fit_release(frame, frame, tmp_path, {})
    original = Predictor.from_release(release, "sklearn")
    optimized = Predictor.from_release(release, "onnx")
    np.testing.assert_allclose(
        original.predict(frame.medical_abstract.tolist()),
        optimized.predict(frame.medical_abstract.tolist()),
        atol=1e-5,
    )


def test_exportacao_preserva_probabilidades_e_publicacao(tmp_path):
    frame = corpus(15)
    release = fit_release(frame, frame, tmp_path, {"origem": "teste sintético"}, min_macro_f1=0)
    assert not (tmp_path / "current.json").exists()
    promote_release(release, tmp_path)
    original = Predictor(tmp_path, "sklearn")
    otimizado = Predictor(tmp_path, "onnx")
    texts = ["TEXTO medico classe 2", "cancer tumor neoplasm", "texto sem vocabulario xyz"]
    np.testing.assert_allclose(original.predict(texts), otimizado.predict(texts), atol=1e-5)
    assert original.version == otimizado.version
    assert original.predict(texts).shape == (3, 5)


def test_rejeita_artefato_alterado(tmp_path):
    frame = corpus(10)
    release = fit_release(frame, frame, tmp_path, {}, min_macro_f1=0)
    promote_release(release, tmp_path)
    (release / "model.onnx").write_bytes(b"corrompido")
    with pytest.raises(ValueError, match="integridade"):
        Predictor(tmp_path)


def test_rejeita_ponteiro_fora_da_raiz(tmp_path):
    (tmp_path / "current.json").write_text(json.dumps({"release": "../fora"}))
    with pytest.raises(ValueError, match="diretório"):
        Predictor(tmp_path)


def test_publicacao_exige_aprovacao_e_preserva_anterior(tmp_path):
    frame = corpus(10)
    first = fit_release(frame, frame, tmp_path, {}, min_macro_f1=0)
    promote_release(first, tmp_path)
    second = fit_release(frame, frame, tmp_path, {}, min_macro_f1=0)
    metadata = json.loads((second / "metadata.json").read_text("utf-8"))
    metadata["aprovado"] = False
    (second / "metadata.json").write_text(json.dumps(metadata), "utf-8")
    with pytest.raises(ValueError, match="aprovação"):
        promote_release(second, tmp_path)
    assert Predictor(tmp_path).version == first.name
    metadata["aprovado"] = True
    (second / "metadata.json").write_text(json.dumps(metadata), "utf-8")
    promote_release(second, tmp_path)
    assert json.loads((tmp_path / "current.json").read_text())["anterior"].endswith(first.name)


def test_falha_de_treino_nao_deixa_release_parcial(tmp_path):
    frame = corpus(10)
    with pytest.raises(ValueError, match="F1"):
        fit_release(frame, frame, tmp_path, {}, min_macro_f1=1)
    assert not list((tmp_path / "releases").iterdir())


def test_publicacao_bloqueia_regressao_na_mesma_validacao(tmp_path):
    palavras = ["tumor cancer", "stomach bowel", "brain nerve", "heart artery", "fever pain"]
    frame = pd.DataFrame(
        [
            {"condition_label": i + 1, "medical_abstract": f"clinical study {word} " * n}
            for i, word in enumerate(palavras)
            for n in range(1, 5)
        ]
    )
    audit = {"sha256_preparados": {"validacao.csv": "mesma-particao"}}
    first = fit_release(frame, frame, tmp_path, audit)
    promote_release(first, tmp_path)
    wrong = frame.copy()
    wrong.condition_label = wrong.condition_label.map({1: 2, 2: 1, 3: 3, 4: 4, 5: 5})
    second = fit_release(wrong, frame, tmp_path, audit, min_macro_f1=0)
    with pytest.raises(ValueError, match="regressão"):
        promote_release(second, tmp_path)
    assert Predictor(tmp_path).version == first.name
