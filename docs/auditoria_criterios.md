# Auditoria final dos critérios de avaliação

Esta conferência segue, item por item, os seis critérios do enunciado. A adaptação autorizada classifica cinco condições médicas do Medical Abstracts TC Corpus. As evidências identificam os ambientes e as versões examinadas; esta avaliação técnica não antecipa a nota da banca.

| Critério | Peso | Conferência e evidência | Resultado |
|---|---:|---|---|
| Modelagem e otimização | 20% | TF-IDF e regressão logística; 5.285 exemplos de ajuste, 1.322 de validação e 2.888 de teste. Exportação ONNX preserva classes e probabilidades. A versão Docker `92cce529` ganhou **3,80× em processo** e **1,24× via HTTP** no p50. [Qualidade](../reports/docker/pos_correcao/qualidade.json), [inferência](../reports/docker/pos_correcao/latencia_modelo.json), [HTTP](../reports/docker/pos_correcao/latencia_http.json) e [reconversão do candidato remoto](../reports/diagnostico_paridade/reconversao_reproduzivel.json). | Atendido |
| CI/CD — GitHub Actions | 15% | [CI 34921095963](https://github.com/callyafiune/Tech-Challenge-fase-3/actions/runs/34921095963), commit `6426446`: lint, **104 testes aprovados**, builds, importação/execução da DAG e stack. A imagem disponibilizada é a mesma validada pelo CI. [Registro](../reports/ci/34921095963/execucao.json), [JUnit](../reports/ci/34921095963/testes.xml) e [workflow](../.github/workflows/ci.yml). | Atendido |
| Orquestração — Airflow | 15% | Quatro tarefas reais: ingestão, treinamento, validação e publicação. Execução identificada, estados `success`, versão publicada e serviços consultados. [DAG](../dags/retreino_medico.py) e [integração local](../reports/docker/pos_correcao/integracao_verificada.json). | Atendido |
| Monitoramento | 20% | API, Prometheus e Grafana em Compose; seis painéis, oito consultas com resultados reais, coleta disponível e conexão da fonte confirmada. Volume, latência e erros estão cobertos. [Smoke](../reports/docker/pos_correcao/smoke_stack.json), [configuração](../monitoring/README.md) e [dashboard](../monitoring/grafana/dashboards/medical-classifier.json). | Atendido |
| Documentação — README | 15% | Escolha AWS ECS Fargate + ALB, inferência em tempo real e retreino separado; execução de modelo, API, Compose, Airflow e benchmarks. Comandos próprios para PowerShell e Bash/Zsh; pré-requisitos do vídeo explicitados. [README](../README.md), [Linux/macOS](execucao_linux_macos.md) e [roteiro](roteiro_star.md). | Atendido |
| Vídeo STAR | 15% | Oito cenas: contexto e impacto da resposta rápida, requisitos, arquitetura, otimização, monitoração configurada, resposta real, DAG/CI, latência e aprendizados. **260,876417 segundos (4min21s)**, H.264/AAC, 1280×720; oito quadros inspecionados e 67 verificações aprovadas. [Vídeo](../reports/video/apresentacao_star.mp4), [verificação](../reports/video/verificacao.json) e [inspeção](../reports/video/inspecao_visual.json). | Atendido |

## Correções decorrentes da auditoria

- A promoção direta também exige avaliação aprovada, versão e hashes correspondentes e ganho de latência finito. O teste reproduziu a publicação indevida após reprovação da validação; a correção preserva o ponteiro nessas condições.
- O exportador rejeita tokenização incompatível e cobre bigramas sem o primeiro, o segundo ou ambos os unigramas. O teste oficial também exige concordância das classes.
- A reconversão do candidato remoto ganhou um [script reproduzível](../scripts/verificar_reconversao.py), executado sem novo ajuste ou alteração dos artefatos originais.
- O benchmark HTTP foi repetido na versão Docker atual: p50 **5,68385 → 4,5707 ms** e p95 **7,60603 → 5,816795 ms**, com 200 chamadas e 20 aquecimentos por motor.
- O guia Linux/macOS deixou de depender da simples substituição do caminho do Python. Os blocos Bash passaram por `bash -n`; a execução completa em Linux é coberta pelo CI. Não houve execução em uma instalação limpa de macOS.
- O vídeo ganhou uma cena de monitoração com configuração, consultas e valores reais. A fonte histórica dos gráficos do host, a versão operacional Docker e o commit do CI são identificados separadamente.

## Verificação complementar

A suíte local atual passou em **104 testes**, com um caso ignorado que depende do Airflow real; nenhuma falha ou erro. Ruff passou na análise e formatação de 22 arquivos. [Resultado JUnit](../reports/testes.xml). Há **17 pareceres concluídos** pelo Claude Code Fable; os achados foram corrigidos ou tratados como decisões justificadas no [registro de revisões](revisoes_adversariais.md).

Os **seis critérios estão atendidos** nas verificações registradas. O CI final repetiu os 104 testes e executou a DAG/stack reais. A [atualização dos containers locais](../reports/auditoria_criterios/runtime_final.json) conferiu as fontes corrigidas, quatro serviços saudáveis e reutilização do mesmo modelo. O [smoke final](../reports/auditoria_criterios/smoke_stack_final.json) preserva uma captura separada das fontes históricas do vídeo. Os oito quadros do MP4 foram inspecionados. O áudio foi verificado quanto a presença, decodificação e amplitude, sem alegação de avaliação perceptiva da locução.

As bibliotecas exigidas estão no pacote/lock: scikit-learn, FastAPI, prometheus-client e Airflow na imagem do orquestrador. O corpus excede 2.000 amostras, a API foi executada em Docker, há comparação de latência, dashboard JSON e histórico semântico. A proposta AWS e a publicação manual GHCR excedem o que foi executado localmente; o enunciado exige a decisão arquitetural documentada, sem exigir provisionamento AWS ou envio ao registro GHCR.
