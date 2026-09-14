"""Retreino semanal com dados isolados e publicação após todos os gates."""

from datetime import UTC, datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="retreino_medico",
    description="Ingere, treina, valida e publica uma versão do classificador médico.",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    schedule="@weekly",
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    is_paused_upon_creation=True,
    default_args={"owner": "equipe-ml", "retries": 1, "retry_delay": timedelta(minutes=1)},
    tags=["classificacao-medica", "retreino"],
) as dag:
    tarefas = {}
    for etapa in ("ingestao", "treinamento", "validacao", "publicacao"):
        tarefas[etapa] = BashOperator(
            task_id=etapa,
            bash_command=(
                "/opt/model-venv/bin/python -m medical_classifier.airflow_tasks "
                + etapa
                + " --execucao '{{ ts_nodash }}'"
            ),
            do_xcom_push=False,
            execution_timeout=timedelta(minutes=15),
        )

    tarefas["ingestao"] >> tarefas["treinamento"] >> tarefas["validacao"] >> tarefas["publicacao"]
