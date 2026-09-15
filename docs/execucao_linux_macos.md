# Execução em Linux e macOS

Estes comandos usam Bash ou Zsh, na raiz do repositório. Requerem Python 3.11, `curl` e Docker com o plugin Compose, com o mecanismo Linux disponível. Se optar por Python 3.12, substitua `python3.11` por `python3.12` na criação do ambiente. O CI verifica a aplicação em Linux; esta documentação não afirma que houve uma instalação limpa em macOS.

## Ambiente Python e configuração

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation .
.venv/bin/python -m pip check
if [ ! -e .env ]; then
  cp .env.example .env
fi
```

O `.env` fornece a senha da demonstração local do Grafana. A instalação do pacote deve ser repetida após alterar `src/`, usando o mesmo comando com `--no-deps --no-build-isolation .`.

`requirements.lock` instala o ambiente completo de inferência, treinamento, build e desenvolvimento e é a opção preferida para reprodução. Ele reúne os locks de cada perfil. A alternativa `.venv/bin/python -m pip install '.[treinamento,dev]'` usa os limites do `pyproject.toml`, sem fixar todas as versões transitivas. O extra `treinamento` é necessário para pipeline e scikit-learn; `scripts/benchmark_http.py` exige **`treinamento` e `dev`**, inclusive HTTPX. A instalação simples `pip install .` atende às dependências de inferência ONNX.

## Dados, modelo e API local

```bash
.venv/bin/python -m medical_classifier.pipeline baixar --dados data/raw
.venv/bin/python -m medical_classifier.pipeline executar --dados data/raw --modelos models --relatorios reports --iteracoes 400
MODEL_BACKEND=onnx .venv/bin/python -m uvicorn medical_classifier.api:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

O último comando permanece em primeiro plano. Em outro terminal, na mesma raiz:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/ready
curl --fail --silent --show-error http://127.0.0.1:8000/predict \
  -H 'Content-Type: application/json' \
  --data '{"texto":"The study evaluated cardiovascular risk factors and the association between hypertension and coronary artery disease."}'
```

Encerre a API local com `Ctrl+C` antes de usar a porta 8000 no Docker. A atribuição `MODEL_BACKEND=onnx` acima vale somente para aquele comando; não é necessário remover uma variável persistente do terminal.

## Stack Docker e monitoramento

```bash
docker info
docker compose config --quiet
docker compose build api pipeline
docker compose up -d
docker compose logs -f pipeline
```

Após o pipeline terminar, encerre apenas o acompanhamento de logs com `Ctrl+C` e execute:

```bash
docker compose ps -a
curl --fail --silent --show-error http://127.0.0.1:8000/ready
.venv/bin/python scripts/smoke_stack.py --requisicoes 100 --tempo-limite 120 --saida reports/smoke_stack_novo.json
```

API: `http://127.0.0.1:8000/docs`; Prometheus: `http://127.0.0.1:9090`; Grafana: `http://127.0.0.1:3000`. As credenciais e os painéis são descritos no [README principal](../README.md) e no [guia de monitoramento](../monitoring/README.md). O treinamento do host e o do Compose possuem armazenamentos próprios; consulte `/ready` para identificar a versão.

O serviço `api` usa o target `runtime`, imagem `medical-classifier:local`, e fixa o motor ONNX. O serviço `pipeline` usa o target `treinamento`, imagem `medical-classifier-treino:local`, com as dependências adicionais do modelo. Um `docker build .` produz o runtime; tarefas de treinamento e diagnóstico de paridade precisam de `--target treinamento`. Consulte [imagens_docker.md](imagens_docker.md) para os perfis e a medição de tamanho.

## Benchmark HTTP em Docker

O primeiro treinamento local também produz `data/prepared/validacao.csv`, usado como entrada do cliente de benchmark. Com a stack ativa:

```bash
docker compose -f docker-compose.yml -f docker-compose.benchmark.yml up -d --no-deps api-original
.venv/bin/python scripts/benchmark_http.py --original http://127.0.0.1:8001 --otimizado http://127.0.0.1:8000 --dados data/prepared/validacao.csv --iteracoes 200 --aquecimento 20 --ambiente docker --saida reports/latencia_http_docker_nova.json
docker compose -f docker-compose.yml -f docker-compose.benchmark.yml stop api-original
```

O serviço `api-original` usa `medical-classifier-treino:local`, construída com o serviço `pipeline`. O cliente HTTP roda no host com as dependências completas instaladas acima. As duas APIs precisam ter carregado a mesma versão. Depois de um retreino, reinicie ambas antes de medir; o script rejeita versões ou motores incompatíveis. O novo relatório tem caminho próprio e não substitui os benchmarks históricos.

Para comparar APIs **do host**, use dois terminais, com os mesmos artefatos `models/`:

```bash
MODEL_BACKEND=onnx .venv/bin/python -m uvicorn medical_classifier.api:app --host 127.0.0.1 --port 8004 --workers 1 --no-access-log
```

```bash
MODEL_BACKEND=sklearn .venv/bin/python -m uvicorn medical_classifier.api:app --host 127.0.0.1 --port 8003 --workers 1 --no-access-log
```

Em um terceiro terminal:

```bash
.venv/bin/python scripts/benchmark_http.py --original http://127.0.0.1:8003 --otimizado http://127.0.0.1:8004 --dados data/prepared/validacao.csv --iteracoes 200 --aquecimento 20 --ambiente host --saida reports/latencia_http_host_nova.json
```

## Airflow

Inicialize primeiro a stack principal para criar os volumes externos de dados/modelos. Execute um produtor de modelos por vez: aguarde o pipeline Compose terminar antes do retreino Airflow.

```bash
docker compose build api pipeline
docker compose -f docker-compose.airflow.yml build airflow
docker compose -f docker-compose.airflow.yml up -d airflow
docker compose -f docker-compose.airflow.yml logs -f airflow
```

O standalone informa suas credenciais iniciais nos logs e atende em `http://127.0.0.1:8080`. Quando estiver pronto, encerre o acompanhamento com `Ctrl+C` e execute:

```bash
docker compose -f docker-compose.airflow.yml exec airflow airflow dags list
DATA_LOGICA="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
docker compose -f docker-compose.airflow.yml exec airflow airflow dags test retreino_medico "$DATA_LOGICA"
docker compose restart api
curl --fail --silent --show-error http://127.0.0.1:8000/ready
```

A data lógica identifica a execução. A DAG é criada pausada; o comando acima executa suas quatro tarefas manualmente. O modelo publicado só entra na API depois do reinício.

O `Dockerfile.airflow` deriva de `medical-classifier-treino:local`, que precisa existir antes do build Airflow. O orquestrador usa `/opt/airflow-venv`; as tarefas usam `/opt/model-venv`, link para o ambiente de treinamento `/opt/venv`. Os ambientes operacionais não duplicam pip; o pip da base Python verifica cada ambiente pelo argumento `--python`, conforme o [guia das imagens](imagens_docker.md).

## Qualidade e encerramento

```bash
.venv/bin/python -m ruff check src tests scripts dags
.venv/bin/python -m ruff format --check src tests scripts dags
.venv/bin/python -m pytest -q
docker compose -f docker-compose.airflow.yml down
docker compose down
```

Os comandos de encerramento preservam os volumes. Encerre também com `Ctrl+C` as APIs do host que tiver iniciado em terminais separados.

## Apresentação em vídeo

O [MP4 publicado](../reports/video/apresentacao_star.mp4) pode ser reproduzido em qualquer sistema com suporte a H.264/AAC. O gerador deste projeto usa Windows PowerShell, `System.Drawing`, `System.Speech` e a voz Microsoft Maria Desktop. Para renderizar novamente, use o ambiente Windows descrito no [roteiro STAR](roteiro_star.md); apenas trocar o caminho do interpretador Python não torna o gerador compatível com Linux/macOS.
