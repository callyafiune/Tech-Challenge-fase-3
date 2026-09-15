# Imagens Docker por responsabilidade

A API ONNX usa uma imagem de inferência própria. As dependências de treinamento, conversão e desenvolvimento deixam de acompanhar cada instância da API. O pipeline e o benchmark scikit-learn usam uma segunda imagem, da qual o Airflow deriva. A mudança preserva `python:3.11.16-slim-bookworm`, as versões das bibliotecas, a normalização textual e os modelos ONNX.

## Perfis e consumidores

| Imagem ou estágio | Conteúdo e finalidade | Consumidor |
|---|---|---|
| `builder` | Hatchling e dependências de construção; produz o wheel do projeto | Somente o build, sem herança pelos estágios operacionais |
| `medical-classifier:local`, target `runtime` | Projeto, FastAPI, Uvicorn, Prometheus Client, NumPy, ONNX Runtime e transitivas | Serviço `api`, motor ONNX |
| `medical-classifier-treino:local`, target `treinamento` | Dependências de inferência e de scikit-learn, pandas, joblib, ONNX, skl2onnx e controle de threads | Serviço `pipeline`, API original do benchmark e diagnóstico de paridade |
| `medical-classifier-airflow:local` | Imagem de treinamento e ambiente separado do Airflow 2.11 | DAG de retreino |

O serviço `api` fixa `MODEL_BACKEND=onnx`. Para servir scikit-learn, use `api-original` no Compose de benchmark; trocar apenas uma variável na imagem de runtime não instala as dependências ausentes. Modelos são lidos do volume compartilhado e não são incluídos no build da imagem.

O target `runtime` é o último estágio do Dockerfile. Portanto, `docker build .` gera a imagem de inferência. Os estágios operacionais copiam os ambientes virtuais necessários; o construtor de wheel não é herdado por eles. A imagem de treinamento contém as ferramentas necessárias ao modelo e não inclui pytest, Ruff ou o cliente HTTP de desenvolvimento.

## Dependências fixadas

| Arquivo | Uso |
|---|---|
| [`requirements-runtime.lock`](../requirements-runtime.lock) | Versões diretas e transitivas necessárias à API ONNX |
| [`requirements-treinamento.lock`](../requirements-treinamento.lock) | Inclui `requirements-runtime.lock` e acrescenta treinamento/conversão |
| [`requirements-build.lock`](../requirements-build.lock) | Construtor de wheel e suas dependências |
| [`requirements.lock`](../requirements.lock) | Ambiente completo do host/CI: treinamento, build e desenvolvimento |

Para reproduzir treinamento, testes e benchmark HTTP no host, a instalação pelo `requirements.lock` continua sendo a opção preferida. Depois, instale o pacote com `pip install --no-deps --no-build-isolation .`. O [README](../README.md#início-rápido) e o [guia Linux/macOS](execucao_linux_macos.md) mostram os comandos com o interpretador da `.venv`.

Como alternativa sem o pin de todas as dependências, `pip install ".[treinamento,dev]"` usa os intervalos do `pyproject.toml`. O extra `treinamento` habilita pipeline, conversão e scikit-learn. O cliente `scripts/benchmark_http.py` exige **treinamento e dev**, pois importa preparação de dados e usa HTTPX. A instalação simples `pip install .` declara apenas as dependências da inferência ONNX. As transitivas permanecem necessárias, inclusive SymPy e Protobuf exigidos pelo ONNX Runtime.

## Construção e execução

Os comandos abaixo funcionam em PowerShell, Bash e Zsh, na raiz do repositório, com `.env` preparado:

```text
docker compose build api pipeline
docker compose up -d
docker compose logs -f pipeline
```

O pipeline precisa concluir antes de a API ficar pronta. Ao reutilizar uma versão íntegra e seus relatórios aprovados, essa etapa não treina outra versão. Para construir diretamente os dois perfis:

```text
docker build --target runtime -t medical-classifier:local .
docker build --target treinamento -t medical-classifier-treino:local .
```

O Airflow exige a imagem de treinamento construída e os volumes criados pela stack principal:

```text
docker compose build api pipeline
docker compose -f docker-compose.airflow.yml build airflow
docker compose -f docker-compose.airflow.yml up -d airflow
```

Após o standalone ficar pronto em `http://127.0.0.1:8080`, uma execução manual em PowerShell usa uma data lógica própria:

```powershell
$dataLogica = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss+00:00')
docker compose -f docker-compose.airflow.yml exec airflow airflow dags test retreino_medico $dataLogica
docker compose restart api
Invoke-RestMethod http://127.0.0.1:8000/ready
```

Execute um produtor de modelos por vez e reinicie a API somente depois de a DAG concluir com sucesso. Para Bash/Zsh, os comandos equivalentes estão no [guia Linux/macOS](execucao_linux_macos.md#airflow). A publicação altera o ponteiro no volume, enquanto o reinício carrega a versão na memória da API.

A API scikit-learn complementar usa a mesma imagem de treinamento e lê o mesmo volume de modelos da API ONNX:

```text
docker compose -f docker-compose.yml -f docker-compose.benchmark.yml up -d --no-deps api-original
```

O cliente do benchmark roda no host com o ambiente completo. Os comandos e os caminhos para novas medições estão no [guia de benchmark HTTP](execucao_linux_macos.md#benchmark-http-em-docker). O diagnóstico de paridade executado em imagem também precisa de `--target treinamento`, pois compara o baseline scikit-learn e o exportador ONNX.

## Ambientes virtuais e verificação

Os ambientes operacionais são criados com `venv --without-pip`. O pip da base oficial Python instala e verifica os pacotes com `--python`, sem duplicar pip/setuptools em cada ambiente virtual. A imagem continua contendo o pip global da base; esta mudança não a torna uma imagem sem gerenciador de pacotes.

Na imagem Airflow, `/opt/model-venv` é um link para `/opt/venv`, preservando os caminhos do ambiente de treinamento. O orquestrador usa `/opt/airflow-venv`. Para conferir as dependências efetivamente instaladas:

```text
docker run --rm --entrypoint /usr/local/bin/python medical-classifier:local -m pip --python /opt/venv/bin/python check
docker run --rm --entrypoint /usr/local/bin/python medical-classifier-treino:local -m pip --python /opt/venv/bin/python check
docker run --rm --entrypoint /usr/local/bin/python medical-classifier-airflow:local -m pip --python /opt/airflow-venv/bin/python check
docker run --rm --entrypoint /usr/local/bin/python medical-classifier-airflow:local -m pip --python /opt/model-venv/bin/python check
```

Um `python -m pip check` comum dentro desses ambientes virtuais não é o comando correto, porque eles não possuem pip próprio. A aprovação do resolvedor também não substitui inferência real, `/ready`, smoke da stack e execução da DAG.

## Medição de tamanho

A [captura anterior](../reports/docker/imagem_enxuta/antes.json) foi registrada em `2026-09-15T22:36:26.564985+00:00`. A [captura das novas imagens](../reports/docker/imagem_enxuta/depois.json), de `2026-09-15T22:50:01.261718+00:00`, usa o mesmo Docker Desktop e plataforma `linux/amd64`:

| Medida | Antes | Depois | Redução |
|---|---:|---:|---:|
| Campo Docker `Size` da imagem da API, bytes | 246.360.476 | 92.232.108 | 62,56% |
| Distribuições Python no ambiente da API | 50 | 23 | 27 distribuições |
| Campo Docker `Size` da imagem Airflow, bytes | 303.130.457 | 214.284.627 | 29,31% |

A imagem separada de treinamento mede **165.226.468 bytes** no mesmo campo `Size`. A API reduziu 154.128.368 bytes; o Airflow reduziu 88.845.830 bytes. O [registro dos builds](../reports/docker/imagem_enxuta/builds.json) identifica comandos, horários e código de saída zero para API/treinamento e Airflow. O [inventário validado do runtime](../reports/docker/imagem_enxuta/runtime-dependencias.json) confirmou 23 distribuições, incluindo o projeto, sem pacotes fora das dependências necessárias nem ferramentas proibidas pelo perfil, e importação dos módulos da API com sucesso.

Os maiores componentes que estavam junto da inferência sem serem usados nesse perfil incluem SciPy, pandas, scikit-learn, ONNX e Ruff. NumPy, ONNX Runtime e SymPy permanecem necessários ao perfil de inferência. A soma dos arquivos de distribuições não equivale ao tamanho da imagem; a redução acima foi calculada pela inspeção das imagens construídas.

O tamanho foi comparado pelo campo `Size` de `docker image inspect`. Esse indicador não representa transferência de rede, tamanho de um arquivo exportado nem consumo exclusivo de disco: camadas podem ser compartilhadas pelas imagens de inferência, treinamento e Airflow. Por exemplo, a inspeção manual usa:

```text
docker image inspect --format "{{.Id}} {{.Size}}" medical-classifier:local
docker image inspect --format "{{.Id}} {{.Size}}" medical-classifier-treino:local
docker image inspect --format "{{.Id}} {{.Size}}" medical-classifier-airflow:local
```

## Proveniência das evidências

Esta alteração de empacotamento é posterior à gravação do vídeo STAR e aos benchmarks históricos. O MP4, seu manifesto e as fontes da captura são preservados. Esses resultados continuam válidos para as versões e imagens ali identificadas; não são apresentados como testes da nova imagem. As medições e verificações desta alteração devem ficar em `reports/docker/imagem_enxuta/`, sem sobrescrever relatórios de qualidade, latência ou monitoração usados pelo vídeo.
