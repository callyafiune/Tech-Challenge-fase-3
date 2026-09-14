"""Verifica isolamento das execuções e publicação somente após validação."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from medical_classifier import airflow_tasks

EXECUCAO = "20260914T000000"


def modulo_tarefas():
    """Obtém o contrato real de execução das tarefas."""
    return airflow_tasks


@pytest.fixture
def etapas_controladas(monkeypatch, tmp_path):
    """Substitui os cálculos pesados, preservando arquivos e gates reais das tarefas."""
    from medical_classifier import pipeline, training

    chamadas = []
    release = tmp_path / "models" / "releases" / "versao-teste"

    def ingerir(raw, prepared):
        chamadas.append(("ingestao", raw, prepared))
        prepared.mkdir(parents=True, exist_ok=True)
        (prepared / "auditoria.json").write_text("{}", encoding="utf-8")
        return str(prepared)

    def treinar(prepared, models):
        chamadas.append(("treinamento", prepared, models))
        release.mkdir(parents=True, exist_ok=True)
        return str(release)

    def validar(versao, prepared, reports):
        chamadas.append(("validacao", versao, prepared, reports))
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "qualidade.json").write_text('{"aprovado": true}', encoding="utf-8")
        return {"qualidade": {"aprovado": True}}

    def publicar(versao, models):
        chamadas.append(("publicacao", versao, models))
        (models / "current.json").write_text(
            json.dumps({"release": versao.relative_to(models).as_posix()}), encoding="utf-8"
        )

    monkeypatch.setattr(pipeline, "ingest", ingerir)
    monkeypatch.setattr(pipeline, "train", treinar)
    monkeypatch.setattr(pipeline, "validate", validar)
    monkeypatch.setattr(training, "promote_release", publicar)
    return chamadas, release


def test_etapas_publicam_somente_apos_validacao(tmp_path, etapas_controladas):
    tarefas = modulo_tarefas()
    dados, modelos = tmp_path / "data", tmp_path / "models"
    chamadas, release = etapas_controladas
    for etapa in ["ingestao", "treinamento", "validacao"]:
        tarefas.execute_step(etapa, EXECUCAO, dados, modelos)
        assert not (modelos / "current.json").exists()
    tarefas.execute_step("publicacao", EXECUCAO, dados, modelos)
    assert [item[0] for item in chamadas] == ["ingestao", "treinamento", "validacao", "publicacao"]
    estado = dados / "runs" / EXECUCAO
    assert chamadas[0][1:] == (estado / "raw", estado / "prepared")
    assert chamadas[2][1:] == (release, estado / "prepared", estado / "reports")
    assert (estado / "release.txt").read_text("utf-8").strip() == str(release.resolve())
    assert json.loads((modelos / "current.json").read_text("utf-8"))["release"] == (
        "releases/versao-teste"
    )


def test_execucoes_guardam_particoes_em_diretorios_distintos(tmp_path, etapas_controladas):
    tarefas = modulo_tarefas()
    chamadas, _release = etapas_controladas
    for execucao in [EXECUCAO, "20260921T000000"]:
        tarefas.execute_step("ingestao", execucao, tmp_path / "data", tmp_path / "models")
    assert chamadas[0][1] != chamadas[1][1]
    assert chamadas[0][2] != chamadas[1][2]


@pytest.mark.parametrize("execucao", ["../fora", "20260914T000000;echo", "", "20269999T000000"])
def test_rejeita_identificador_de_execucao_invalido(tmp_path, execucao):
    tarefas = modulo_tarefas()
    with pytest.raises(ValueError, match="execução"):
        tarefas.execute_step("ingestao", execucao, tmp_path / "data", tmp_path / "models")
    assert not (tmp_path / "data").exists()


def test_publicacao_sem_validacao_falha(tmp_path, etapas_controladas):
    tarefas = modulo_tarefas()
    dados, modelos = tmp_path / "data", tmp_path / "models"
    tarefas.execute_step("ingestao", EXECUCAO, dados, modelos)
    tarefas.execute_step("treinamento", EXECUCAO, dados, modelos)
    with pytest.raises(ValueError, match="validação"):
        tarefas.execute_step("publicacao", EXECUCAO, dados, modelos)
    assert not (modelos / "current.json").exists()


def test_falha_de_validacao_remove_aprovacao_anterior(monkeypatch, tmp_path, etapas_controladas):
    from medical_classifier import pipeline

    tarefas = modulo_tarefas()
    dados, modelos = tmp_path / "data", tmp_path / "models"
    for etapa in ["ingestao", "treinamento", "validacao"]:
        tarefas.execute_step(etapa, EXECUCAO, dados, modelos)

    def falhar(*args):
        raise ValueError("Validação reprovada.")

    monkeypatch.setattr(pipeline, "validate", falhar)
    with pytest.raises(ValueError, match="reprovada"):
        tarefas.execute_step("validacao", EXECUCAO, dados, modelos)
    with pytest.raises(ValueError, match="validação"):
        tarefas.execute_step("publicacao", EXECUCAO, dados, modelos)
    assert not (modelos / "current.json").exists()


def test_treinamento_reexecutado_invalida_validacao(tmp_path, etapas_controladas):
    tarefas = modulo_tarefas()
    dados, modelos = tmp_path / "data", tmp_path / "models"
    for etapa in ["ingestao", "treinamento", "validacao", "treinamento"]:
        tarefas.execute_step(etapa, EXECUCAO, dados, modelos)
    with pytest.raises(ValueError, match="validação"):
        tarefas.execute_step("publicacao", EXECUCAO, dados, modelos)


def test_estado_nao_permite_publicar_versao_externa(tmp_path, etapas_controladas):
    tarefas = modulo_tarefas()
    dados, modelos = tmp_path / "data", tmp_path / "models"
    for etapa in ["ingestao", "treinamento", "validacao"]:
        tarefas.execute_step(etapa, EXECUCAO, dados, modelos)
    (dados / "runs" / EXECUCAO / "release.txt").write_text(str(tmp_path), encoding="utf-8")
    with pytest.raises(ValueError, match="modelos"):
        tarefas.execute_step("publicacao", EXECUCAO, dados, modelos)


def test_cli_usa_diretorios_do_ambiente(monkeypatch, tmp_path, etapas_controladas, capsys):
    tarefas = modulo_tarefas()
    dados, modelos = tmp_path / "data", tmp_path / "models"
    monkeypatch.setenv("MEDICAL_DATA_DIR", str(dados))
    monkeypatch.setenv("MODEL_DIR", str(modelos))
    tarefas.main(["ingestao", "--execucao", EXECUCAO])
    assert (dados / "runs" / EXECUCAO / "prepared" / "auditoria.json").exists()
    assert json.loads(capsys.readouterr().out)["etapa"] == "ingestao"


@pytest.mark.parametrize("resultado", [{"qualidade": {"aprovado": False}}, {"qualidade": {}}])
def test_reprova_resultado_sem_aprovacao_explicita(
    monkeypatch, tmp_path, etapas_controladas, resultado
):
    from medical_classifier import pipeline

    dados, modelos = tmp_path / "data", tmp_path / "models"
    for etapa in ["ingestao", "treinamento"]:
        airflow_tasks.execute_step(etapa, EXECUCAO, dados, modelos)
    monkeypatch.setattr(pipeline, "validate", lambda *args: resultado)
    with pytest.raises(ValueError, match="validação"):
        airflow_tasks.execute_step("validacao", EXECUCAO, dados, modelos)
    with pytest.raises(ValueError, match="validação"):
        airflow_tasks.execute_step("publicacao", EXECUCAO, dados, modelos)
    assert not (modelos / "current.json").exists()


def test_estado_sem_treinamento_exibe_erro_descritivo(tmp_path):
    with pytest.raises(ValueError, match="treinamento"):
        airflow_tasks.execute_step("validacao", EXECUCAO, tmp_path / "data", tmp_path / "models")


def test_versao_registrada_inexistente_exibe_erro_descritivo(tmp_path):
    dados, modelos = tmp_path / "data", tmp_path / "models"
    estado = dados / "runs" / EXECUCAO
    estado.mkdir(parents=True)
    (estado / "release.txt").write_text(str(modelos / "releases" / "ausente"), encoding="utf-8")
    with pytest.raises(ValueError, match="não existe"):
        airflow_tasks.execute_step("validacao", EXECUCAO, dados, modelos)


def test_etapas_reais_treinam_validam_e_publicam_artefato_integro(tmp_path):
    import hashlib

    import pandas as pd

    from medical_classifier.serving import Predictor

    dados, modelos = tmp_path / "data", tmp_path / "models"
    preparado = dados / "runs" / EXECUCAO / "prepared"
    preparado.mkdir(parents=True)
    palavras = ["tumor cancer", "stomach bowel", "brain nerve", "heart artery", "fever pain"]
    for indice, particao in enumerate(["treino", "validacao", "teste"]):
        frame = pd.DataFrame(
            [
                {
                    "condition_label": classe + 1,
                    "medical_abstract": (
                        f"clinical study {palavra} " * (n + indice) + f" {particao} exemplo {n}"
                    ),
                }
                for classe, palavra in enumerate(palavras)
                for n in range(1, 5)
            ]
        )
        frame.to_csv(preparado / f"{particao}.csv", index=False)
    (preparado / "auditoria.json").write_text(
        json.dumps(
            {
                "origem": "teste sintético das etapas reais",
                "sha256_preparados": {
                    nome: hashlib.sha256((preparado / nome).read_bytes()).hexdigest()
                    for nome in ["treino.csv", "validacao.csv", "teste.csv"]
                },
            }
        ),
        encoding="utf-8",
    )
    airflow_tasks.execute_step("treinamento", EXECUCAO, dados, modelos)
    assert not (modelos / "current.json").exists()
    airflow_tasks.execute_step("validacao", EXECUCAO, dados, modelos)
    assert not (modelos / "current.json").exists()
    airflow_tasks.execute_step("publicacao", EXECUCAO, dados, modelos)
    predictor = Predictor(modelos)
    probabilities = predictor.predict(["clinical study heart artery"])
    assert probabilities.shape == (1, 5)
    assert probabilities.argmax(axis=1).tolist() == [3]
    quality = json.loads((preparado.parent / "reports" / "qualidade.json").read_text("utf-8"))
    assert quality["aprovado"] is True


def test_dag_real_tem_dependencias_e_limites_de_execucao():
    pytest.importorskip("airflow", reason="Airflow é validado em seu próprio contêiner no CI.")
    from airflow.models import DagBag

    bag = DagBag(
        dag_folder=str(Path(__file__).resolve().parents[1] / "dags"), include_examples=False
    )
    assert not bag.import_errors
    dag = bag.dags["retreino_medico"]
    assert dag.max_active_runs == 1
    assert dag.catchup is False
    assert set(dag.task_ids) == {"ingestao", "treinamento", "validacao", "publicacao"}
    assert dag.get_task("publicacao").upstream_task_ids == {"validacao"}
    assert dag.get_task("validacao").upstream_task_ids == {"treinamento"}
    assert dag.get_task("treinamento").upstream_task_ids == {"ingestao"}
    assert all(task.retries == 1 for task in dag.tasks)
