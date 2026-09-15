# Classificação de condições médicas — Tech Challenge Fase 3

![Python](https://img.shields.io/badge/Python-3.11-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-0.116-009688)
![ONNX Runtime](https://img.shields.io/badge/ONNX%20Runtime-1.23-005CED)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)
![Airflow](https://img.shields.io/badge/Airflow-2.11-017CEE)
[![GitHub Actions](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/workflows/ci.yml/badge.svg)](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/workflows/ci.yml)

API para classificar **resumos médicos em inglês** com TF-IDF e regressão logística, otimizada com **ONNX Runtime**. O projeto inclui treinamento reproduzível, retreino no Airflow, imagens Docker, CI/CD e monitoramento com Prometheus e Grafana.

São cinco categorias: neoplasias, doenças do sistema digestivo, doenças do sistema nervoso, doenças cardiovasculares e condições patológicas gerais. **Uso acadêmico:** o serviço classifica o assunto do resumo; não determina urgência, diagnóstico ou risco clínico.

Os dados são do [Medical Abstracts TC Corpus](https://github.com/sebischair/Medical-Abstracts-TC-Corpus), de Tim Schopf, Daniel Braun e Florian Matthes, sob [CC BY-SA 3.0](https://github.com/sebischair/Medical-Abstracts-TC-Corpus/blob/70a2d9106c724729be8b3c4ddb00d1b14ec300c8/LICENSE). O pipeline baixa uma revisão fixa e verifica os arquivos por SHA-256. Origem, preparação e limitações estão na [documentação do modelo](docs/model_card.md).

## Início rápido

Requisitos: **Python 3.11**, Git, Docker com Compose e internet para o corpus e as dependências. Comandos para **PowerShell no Windows**; veja o [guia Linux/macOS](docs/execucao_linux_macos.md) para Bash/Zsh.

```powershell
git clone https://github.com/callyafiune/Tech-Challenge-fase-3.git
cd Tech-Challenge-fase-3
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation .
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
docker compose build api pipeline
docker compose up -d
docker compose logs -f pipeline
```

Aguarde o pipeline terminar e encerre apenas o acompanhamento de logs com `Ctrl+C`. Ele treina na primeira execução e reutiliza uma versão íntegra nas seguintes. Os volumes Docker são separados dos artefatos do host. A API usa a imagem ONNX `medical-classifier:local`; pipeline e benchmark scikit-learn usam `medical-classifier-treino:local`. Perfis e dependências: [imagens Docker](docs/imagens_docker.md).

| Serviço | Endereço local |
|---|---|
| API e documentação interativa | http://127.0.0.1:8000/docs |
| Prometheus | http://127.0.0.1:9090 |
| Grafana | http://127.0.0.1:3000 |

O Grafana usa `admin` / `desenvolvimento-local`, conforme `.env.example`, e provisiona seis painéis de volume, prontidão, coleta, latência e erros. As portas são publicadas somente em loopback. Execute `docker compose down` para encerrar preservando os volumes.

## Classificar e verificar a operação

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ready
$corpo = @{ texto = 'The study evaluated cardiovascular risk factors and the association between hypertension and coronary artery disease.' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/predict -ContentType 'application/json' -Body $corpo
.\.venv\Scripts\python.exe scripts/smoke_stack.py --requisicoes 100 --tempo-limite 120 --saida reports/smoke_stack_novo.json
```

`POST /predict` aceita `texto` com 20 a 20.000 caracteres e retorna classe, cinco probabilidades, versão e motor. `/health` verifica o processo, `/ready` verifica o modelo carregado e `/metrics` expõe métricas HTTP. O smoke consulta a API, o Prometheus e os painéis reais do Grafana. Consulte o [contrato e as limitações](docs/model_card.md) e a [configuração de monitoramento](monitoring/README.md).

## Treinamento e Airflow

O ambiente instalado pelo lock inclui treinamento, build e desenvolvimento. Para treinar no host e gravar novos relatórios:

```powershell
.\.venv\Scripts\python.exe -m medical_classifier.pipeline executar --dados data/raw --modelos models --relatorios reports/nova_execucao --iteracoes 400
```

Para iniciar o retreino no Airflow, aguarde o pipeline Compose terminar:

```powershell
docker compose build api pipeline
docker compose -f docker-compose.airflow.yml build airflow
docker compose -f docker-compose.airflow.yml up -d airflow
docker compose -f docker-compose.airflow.yml logs -f airflow
```

O Airflow atende em http://127.0.0.1:8080 e informa as credenciais iniciais nos logs. A DAG `retreino_medico` executa **ingestão → treinamento → validação → publicação**. Depois de publicar uma versão, reinicie a API com `docker compose restart api`. Execute um produtor de modelos por vez. Comandos da DAG, ambientes e retenção: [guia de execução](docs/execucao_linux_macos.md#airflow), [imagens](docs/imagens_docker.md) e [arquitetura](docs/arquitetura.md).

## Resultados e validação

Medições da versão Docker **`20260914T232434-92cce529`**, comparando os dois motores no mesmo experimento:

| Medida | scikit-learn | ONNX |
|---|---:|---:|
| Acurácia no teste oficial | 0,639197 | 0,639197 |
| F1 macro no teste oficial | 0,638544 | 0,638544 |
| p50 de inferência em processo | 1,317915 ms | 0,346612 ms |
| p50 HTTP | 5,68385 ms | 4,5707 ms |

O ganho foi **3,80× em processo** e **1,24× no HTTP**. Fontes: [qualidade](reports/docker/pos_correcao/qualidade.json), [inferência](reports/docker/pos_correcao/latencia_modelo.json) e [HTTP](reports/docker/pos_correcao/latencia_http.json). As medições têm versões e ambientes identificados; não estabelecem capacidade sob concorrência. A separação atual das imagens é posterior a esses benchmarks e tem [evidências próprias](docs/imagens_docker.md#medição-de-tamanho).

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests scripts dags
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts dags
.\.venv\Scripts\python.exe -m pytest -q
```

O [CI](.github/workflows/ci.yml) verifica código, imagens, DAG e stack. A [entrega manual](.github/workflows/entrega.yml) publica no GHCR a imagem de runtime validada pelo CI, sem reconstruí-la; essa publicação ainda não foi comprovada. Para reproduzir os benchmarks HTTP, siga o [guia](docs/execucao_linux_macos.md#benchmark-http-em-docker) com o ambiente completo de treinamento e desenvolvimento.

## Arquitetura de produção

A proposta usa **AWS ECS Fargate + Application Load Balancer** para inferência síncrona, com prontidão em `/ready`, imagens no ECR e modelos versionados em S3. Fargate reduz a administração de servidores; o retreino batch fica separado para não disputar recursos com a API. **A infraestrutura AWS não foi provisionada.** Decisões, custos operacionais e limites estão em [arquitetura.md](docs/arquitetura.md).

## Vídeo e documentação

O [vídeo STAR](reports/video/apresentacao_star.mp4) tem **4min21s**, oito cenas e narração sintética em português Brasil. Apresenta API, DAG, otimização e configuração de monitoração com consultas reais. O [manifesto](reports/video/evidencias.json), as [67 verificações](reports/video/verificacao.json) e a [inspeção visual](reports/video/inspecao_visual.json) identificam a captura. O vídeo preserva as versões e imagens do momento da gravação.

- [Modelo, corpus e limitações](docs/model_card.md).
- [Arquitetura e operação](docs/arquitetura.md).
- [Imagens Docker e dependências](docs/imagens_docker.md).
- [Execução Linux/macOS e benchmarks](docs/execucao_linux_macos.md).
- [Roteiro e reprodução do vídeo no Windows](docs/roteiro_star.md).
- [Critérios de avaliação](docs/auditoria_criterios.md) e [matriz de rastreabilidade](docs/matriz_rastreabilidade.md).
