"""Importa a DAG sem executar tarefas ou montar volumes persistentes."""
import contextlib
import json
import sys
with contextlib.redirect_stdout(sys.stderr):
    from airflow.models import DagBag
    bag = DagBag(dag_folder="/opt/airflow/dags", include_examples=False)
    assert not bag.import_errors, bag.import_errors
    dag = bag.dags["retreino_medico"]
    esperado = {"ingestao": [], "treinamento": ["ingestao"], "validacao": ["treinamento"], "publicacao": ["validacao"]}
    obtido = {t.task_id: sorted(t.upstream_task_ids) for t in dag.tasks}
    assert obtido == esperado, obtido
    assert dag.catchup is False and dag.max_active_runs == 1 and dag.max_active_tasks == 1
    assert all(t.retries == 1 for t in dag.tasks)
    assert all(t.bash_command.startswith("/opt/model-venv/bin/python -m medical_classifier.airflow_tasks ") for t in dag.tasks)
print(json.dumps({"sucesso": True, "dag": dag.dag_id, "tarefas": obtido, "max_active_runs": dag.max_active_runs, "max_active_tasks": dag.max_active_tasks, "catchup": dag.catchup, "retreino_executado": False, "erros_importacao": bag.import_errors}, ensure_ascii=False))
