# Monitoramento local

O Compose publica a API em `http://127.0.0.1:8000`, o Prometheus em
`http://127.0.0.1:9090` e o Grafana em `http://127.0.0.1:3000`. Copie
`.env.example` para `.env`, configure a senha local do Grafana e execute
`docker compose up --build -d`. A primeira execução baixa o corpus e treina
o modelo antes de iniciar a API. As próximas execuções usam `--reutilizar`:
um modelo publicado, aprovado e íntegro é reaproveitado sem novo treino.
Sem versão publicada, o pipeline reutiliza o corpus do volume `dados` para
treinar outra versão. Uma versão publicada inválida interrompe a inicialização,
permitindo investigar a integridade antes de um retreino explícito.
O retreino explícito pela linha de comando e pelo
Airflow continua executando todas as etapas.

Os volumes `modelos`, `prometheus-dados` e `grafana-dados` preservam os
artefatos, as séries temporais e o banco do Grafana, respectivamente. A API
monta o volume de modelos somente para leitura. `docker compose down`
encerra os serviços e preserva os volumes; a opção `-v` também apaga esses
dados. A senha do Grafana definida no primeiro início é persistida no banco;
alterar apenas `.env` não muda a senha de uma instalação já inicializada.

Faça login no Grafana com as credenciais de `.env` e abra o dashboard
**Classificação médica — operação da API**, na pasta **Tech Challenge Fase 3**.
A fonte de dados e os seis painéis são provisionados automaticamente:

1. Total de chamadas a `POST /predict` desde o início do processo.
2. Disponibilidade da coleta `up` do Prometheus.
3. Prontidão do modelo, combinando `model_ready` e a coleta ativa `up`.
4. Taxa de chamadas de classificação por segundo.
5. Latência HTTP p50 e p95, estimada a partir do histograma.
6. Percentuais de erros 4xx e 5xx nas classificações.

As consultas de classificação filtram a rota `/predict` e o método `POST`.
Os acessos a `/health`, `/ready` e `/metrics` não distorcem esses painéis.
Sem chamadas suficientes para duas coletas, o histograma ainda não permite
estimar quantis e o painel de latência pode ficar vazio. A coleta ocorre a
cada cinco segundos; o dashboard usa uma janela de taxa de pelo menos
20 segundos, que cresce conforme o intervalo exibido e a resolução.
O painel de disponibilidade da coleta não substitui a prontidão
do modelo, nem mede a qualidade das predições.

Execute `python scripts/smoke_stack.py` após subir a stack. O script consulta
a configuração resolvida do Compose, inclusive portas e credenciais locais,
sem gravar a senha no relatório. Ele gera chamadas válidas espaçadas de um
segundo e entradas inválidas, aguarda coletas reais, confirma a conexão
entre Grafana e Prometheus e executa as consultas de todos os painéis com
a janela mínima de 20 segundos. Todas as consultas usam o instante da coleta
confirmada pelo Prometheus, registrado em `instante_metricas_utc`; assim,
uma demora na inicialização do Grafana preserva a janela dos dados de teste.
A evidência fica em
`reports/smoke_stack.json`. Use `--requisicoes 100` para gerar mais chamadas.

Os relatórios produzidos dentro do pipeline ficam no volume `dados`. Para
extraí-los preservando os resultados de outras execuções do repositório:

```powershell
New-Item -ItemType Directory -Force reports/docker
docker compose cp pipeline:/app/data/reports/. ./reports/docker/
```

Esse comando funciona também quando o container do pipeline já encerrou
com sucesso e copia `qualidade.json` e `latencia_modelo.json`. O smoke
executado no host grava sua evidência diretamente em `reports/`.

O dashboard JSON é a fonte versionada. Para alterar o layout, edite
`grafana/dashboards/medical-classifier.json`; mudanças locais feitas pela
interface não são persistidas sobre o provisionamento. O dashboard não
inclui textos médicos, nomes de pacientes ou identificadores de chamadas.
A releitura dos arquivos ocorre a cada 20 segundos, inclusive em volumes
montados pelo Docker Desktop no Windows.

As versões foram fixadas após consulta às fontes oficiais em 14/09/2026:
[Python 3.11.16](https://hub.docker.com/_/python),
[Prometheus 3.14.0](https://github.com/prometheus/prometheus/releases/tag/v3.14.0) e
[Grafana 13.2.1](https://github.com/grafana/grafana/releases/tag/v13.2.1).
A ordem de inicialização segue as
[condições de dependência do Docker Compose](https://docs.docker.com/compose/how-tos/startup-order/)
e o dashboard usa o
[provisionamento de arquivos do Grafana](https://grafana.com/docs/grafana/latest/administration/provisioning/).
