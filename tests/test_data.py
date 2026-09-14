"""Verificações do contrato e da separação dos dados."""

import pandas as pd
import pytest

from medical_classifier.data import CLASSES, download_data, prepare_data, read_corpus


def corpus(n=12):
    return pd.DataFrame(
        [
            {
                "condition_label": classe,
                "medical_abstract": f"texto medico classe {classe} amostra {i}",
            }
            for classe in CLASSES
            for i in range(n)
        ]
    )


def test_rejeita_rotulo_desconhecido(tmp_path):
    frame = corpus()
    frame.loc[0, "condition_label"] = 9
    path = tmp_path / "dados.csv"
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="rótulo"):
        read_corpus(path)


@pytest.mark.parametrize("texto", [None, "", "   "])
def test_rejeita_texto_ausente(tmp_path, texto):
    frame = corpus()
    frame.loc[0, "medical_abstract"] = texto
    path = tmp_path / "dados.csv"
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="texto"):
        read_corpus(path)


def test_split_sem_vazamento_e_reproduzivel(tmp_path):
    treino = corpus()
    teste = corpus(2)
    treino.to_csv(tmp_path / "medical_tc_train.csv", index=False)
    teste.to_csv(tmp_path / "medical_tc_test.csv", index=False)
    a = prepare_data(tmp_path, min_samples=0)
    b = prepare_data(tmp_path, min_samples=0)
    assert a.audit["sobreposicoes_removidas_treino"] == 10
    assert len(a.test) == 10
    for x, y in [(a.train, a.validation), (a.train, a.test), (a.validation, a.test)]:
        assert set(x.medical_abstract).isdisjoint(set(y.medical_abstract))
    pd.testing.assert_frame_equal(a.train, b.train)


def test_corpus_pequeno_nao_e_aceito_como_entrega(tmp_path):
    corpus().to_csv(tmp_path / "medical_tc_train.csv", index=False)
    corpus(2).to_csv(tmp_path / "medical_tc_test.csv", index=False)
    with pytest.raises(ValueError, match="2.000"):
        prepare_data(tmp_path)


def test_audita_ambiguidades_sem_alterar_teste(tmp_path):
    treino = corpus()
    iguais = treino.iloc[[4, 4]].copy()
    conflito = treino.iloc[[5]].copy()
    conflito.condition_label = 2
    pd.concat([treino, iguais, conflito]).to_csv(tmp_path / "medical_tc_train.csv", index=False)
    teste = corpus(2)
    ambiguo = teste.iloc[[0]].copy()
    ambiguo.condition_label = 2
    pd.concat([teste, ambiguo]).to_csv(tmp_path / "medical_tc_test.csv", index=False)
    result = prepare_data(tmp_path, min_samples=0)
    assert result.audit["rotulos_conflitantes_removidos"] == 2
    assert result.audit["duplicatas_removidas_treino"] == 2
    assert result.audit["teste_textos_unicos"] == 10
    assert result.audit["teste_linhas_ambiguas"] == 2
    assert result.audit["teste_teto_acuracia_deterministica"] == pytest.approx(10 / 11)
    assert len(result.test) == 11


def test_download_rejeita_arquivo_local_corrompido(tmp_path):
    (tmp_path / "LICENSE").write_text("adulterado")
    with pytest.raises(ValueError, match="integridade"):
        download_data(tmp_path)
